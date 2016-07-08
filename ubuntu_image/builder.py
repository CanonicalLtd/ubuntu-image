"""Flow for building a disk image."""


import os
import shutil

from tempfile import TemporaryDirectory
from ubuntu_image.helpers import GiB, run
from ubuntu_image.image import Image
from ubuntu_image.state import State


SPACE = ' '


class BaseImageBuilder(State):
    def __init__(self):
        super().__init__()
        self._tmpdir = self.resources.enter_context(TemporaryDirectory())
        self._next.append(self.populate_rootfs_contents)
        # Information passed between states.
        self.rootfs = None
        self.rootfs_size = 0
        self.bootfs = None
        self.bootfs_size = 0

    def populate_rootfs_contents(self):
        # Create and populate a local directory containing the root file
        # system contents.
        self.rootfs = os.path.join(self._tmpdir, 'root')
        os.makedirs(self.rootfs)
        # XXX For now just put some dummy contents there to verify the basic
        # approach.
        for path, contents in {
                'foo': 'this is foo',
                'bar': 'this is bar',
                'baz/buz': 'some bazz buzz',
                }.items():
            rooted_path = os.path.join(self.rootfs, path)
            dirname = os.path.dirname(path)
            if len(dirname) > 0:
                os.makedirs(os.path.dirname(rooted_path), exist_ok=True)
            with open(rooted_path, 'w', encoding='utf-8') as fp:
                fp.write(contents)
        # Mount point for /boot.
        os.mkdir(os.path.join(self.rootfs, 'boot'))
        self._next.append(self.calculate_rootfs_size)

    def _calculate_dirsize(self, path):
        total = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                total += os.path.getsize(os.path.join(dirpath, filename))
        # Fudge factor for incidentals.
        total *= 1.5
        return total

    def calculate_rootfs_size(self):
        # Calculate the size of the root file system.  Basically, I'm trying
        # to reproduce du(1) close enough without having to call out to it and
        # parse its output.
        self.rootfs_size = self._calculate_dirsize(self.rootfs)
        self._next.append(self.populate_bootfs_contents)

    def populate_bootfs_contents(self):
        # Create the boot file system contents.
        self.bootfs = os.path.join(self._tmpdir, 'boot')
        os.makedirs(self.bootfs)
        for path, contents in {
                'other': 'other',
                'boot/qux': 'boot qux',
                'boot/qay': 'boot qay',
                }.items():
            booted_path = os.path.join(self.bootfs, path)
            dirname = os.path.dirname(path)
            if len(dirname) > 0:
                os.makedirs(os.path.dirname(booted_path), exist_ok=True)
            with open(booted_path, 'w', encoding='utf-8') as fp:
                fp.write(contents)
        self._next.append(self.calculate_bootfs_size)

    def calculate_bootfs_size(self):
        self.bootfs_size = self._calculate_dirsize(self.bootfs)
        self._next.append(self.prepare_filesystems)

    def prepare_filesystems(self):
        self.images = os.path.join(self._tmpdir, '.images')
        os.makedirs(self.images)
        # The image for the boot partition.
        self.boot_img = os.path.join(self.images, 'boot.img')
        run('dd if=/dev/zero of={} count=0 bs=1GB seek=1'.format(
            self.boot_img))
        run('mkfs.vfat {}'.format(self.boot_img))
        # The image for the root partition.
        self.root_img = os.path.join(self.images, 'root.img')
        run('dd if=/dev/zero of={} count=0 bs=1GB seek=2'.format(
            self.root_img))
        # We defer creating the root file system image because we have to
        # populate it at the same time.  See mkfs.ext4(8) for details.
        self._next.append(self.populate_filesystems)

    def populate_filesystems(self):
        # The boot file system is VFAT.
        sourcefiles = SPACE.join(
            os.path.join(self.bootfs, filename)
            for filename in os.listdir(self.bootfs)
            )
        run('mcopy -i {} {} ::'.format(self.boot_img, sourcefiles),
            env=dict(MTOOLS_SKIP_CHECK='1'))
        # The root partition needs to be ext4, which can only be populated at
        # creation time.
        run('mkfs.ext4 {} -d {}'.format(self.root_img, self.rootfs))
        self._next.append(self.make_disk)

    def make_disk(self):
        self.disk_img = os.path.join(self.images, 'disk.img')
        image = Image(self.disk_img, GiB(4))
        # Create BIOS boot partition
        #
        # The partition is 1MiB in size, as recommended by various
        # partitioning guides.  The actual required size is much, much
        # smaller.
        #
        # https://www.gnu.org/software/grub/manual/html_node/BIOS-installation.html#BIOS-installation
        # image.partition(new='1:4MiB:+1MiB')
        # image.partition(typecode='1:21686148-6449-6E6F-744E-656564454649')
        # image.partition(change_name='1:grub')
        # image.copy_blob(self.boot_img,
        #                 bs='1MiB', seek=4, count=1, conv='notrunc')
        # Create EFI system partition
        #
        # TODO: switch to 512MiB as recommended by the standard
        image.partition(new='2:5MiB:+64MiB')
        image.partition(typecode='2:C12A7328-F81F-11D2-BA4B-00A0C93EC93B')
        image.partition(change_name='2:system-boot')
        image.copy_blob(self.boot_img,
                        bs='1MB', seek=4, count=64, conv='notrunc')
        # Create main snappy writable partition
        image.partition(new='3:72MiB:+3646MiB')
        image.partition(typecode='3:0FC63DAF-8483-4772-8E79-3D69D8477DE4')
        image.partition(change_name='3:writable')
        image.copy_blob(self.root_img,
                        bs='1MiB', seek=72, count=3646, conv='notrunc')
        self._next.append(self.finish)

    def finish(self):
        # Copy the completed disk image to the current directory, since the
        # temporary scratch directory is about to get removed.
        shutil.copy(self.disk_img, os.getcwd())
        self._next.append(self.close)
