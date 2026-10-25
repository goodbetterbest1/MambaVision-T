#!/usr/bin/env python3
"""Safely extract downloaded source images, without downloading or redistributing data."""
from __future__ import annotations

import argparse
import os
import posixpath
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff'}
MAX_TOTAL_BYTES = 20 * 1024 ** 3
MAX_IMAGE_BYTES = 256 * 1024 ** 2


def prepare_archive(archive: Path, output: Path) -> list[Path]:
    archive = Path(archive).expanduser()
    output = Path(output).expanduser().resolve()
    with zipfile.ZipFile(archive) as package:
        candidates = []
        for info in package.infolist():
            path = PurePosixPath(info.filename.replace('\\', '/'))
            if path.is_absolute() or '..' in path.parts or any(':' in part for part in path.parts):
                raise ValueError('Unsafe archive path: ' + info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('Symbolic links are not accepted: ' + info.filename)
            if info.is_dir() or '__MACOSX' in path.parts or path.name.startswith('.'):
                continue
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            if info.flag_bits & 1:
                raise ValueError('Encrypted images are not supported')
            if not 0 < info.file_size <= MAX_IMAGE_BYTES:
                raise ValueError('Invalid or oversized image: ' + info.filename)
            candidates.append((info, path))
        if not candidates:
            raise ValueError('No supported source images found in archive')
        if sum(info.file_size for info, _ in candidates) > MAX_TOTAL_BYTES:
            raise ValueError('Archive exceeds the 20 GiB extraction limit')
        common_prefix = posixpath.commonpath([str(path.parent) for _, path in candidates])
        prefix = None if common_prefix in ('', '.') else PurePosixPath(common_prefix)
        plans, names = [], set()
        for info, path in candidates:
            relative = path if prefix is None else path.relative_to(prefix)
            key = relative.as_posix().casefold()
            if key in names:
                raise ValueError('Duplicate/case-conflicting image path: ' + str(relative))
            names.add(key)
            target = output.joinpath(*relative.parts)
            if output not in target.resolve().parents:
                raise ValueError('Image destination escapes the output directory')
            if target.exists() or target.is_symlink():
                raise FileExistsError('Refusing to overwrite existing image: ' + str(target))
            plans.append((info, target))
        # Preflight every destination before writing any image. Original files are never changed.
        written = []
        for info, target in plans:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.extract-', delete=False) as handle:
                    temporary = Path(handle.name)
                    with package.open(info) as source:
                        shutil.copyfileobj(source, handle, length=1024 * 1024)
                if temporary.stat().st_size != info.file_size:
                    raise ValueError('Incomplete extraction: ' + info.filename)
                if target.exists():
                    raise FileExistsError('Destination appeared during extraction: ' + str(target))
                os.replace(temporary, target)
                written.append(target)
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()
        return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path, help='Images.zip downloaded from the original provider')
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parent.parent / 'data/images')
    args = parser.parse_args()
    try:
        files = prepare_archive(args.archive, args.out)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.exit(1, f'Image preparation failed: {error}\n')
    print(f'Prepared {len(files)} source images in {args.out.expanduser().resolve()}')
    print('Only common wrapper directories were removed; filenames and image bytes were not modified.')
    print('This is extraction only, not clinical/annotation validation. Start run_local.py to annotate.')


if __name__ == '__main__':
    main()
