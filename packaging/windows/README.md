# Windows Package Builder

<!-- Preserve the historical source and attribution. -->

> **Legacy packaging reference**: This describes the inherited Pixelle-Video packaging pipeline, not a released or validated FrameWeave installer. Current FrameWeave installation and startup instructions are in the [project README](../../README.md).

Automated build system for creating Windows portable packages of Pixelle-Video.

## Quick Start

### Prerequisites

- Python 3.11+ (for running the build script)
- PyYAML: `pip install pyyaml`
- Internet connection (for downloading Python, FFmpeg, etc.)

### Build Package

```bash
# Basic build
python packaging/windows/build.py

# Build with China mirrors (faster in China)
python packaging/windows/build.py --cn-mirror

# Custom output directory
python packaging/windows/build.py --output /path/to/output
```

## Configuration

Edit `config/build_config.yaml` to customize:

- Python version
- FFmpeg version
- Excluded files/folders
- Build options
- Mirror settings

## Output

The build process creates:

```
dist/windows/
├── Pixelle-Video-v*-win64/             # Build directory (version number varies)
│   ├── python/                         # Python embedded
│   ├── tools/                          # FFmpeg, etc.
│   ├── Pixelle-Video/                  # Project files
│   ├── data/                           # User data (empty)
│   ├── output/                         # Output (empty)
│   ├── start.bat                       # Main launcher
│   ├── start_api.bat                   # API launcher
│   ├── start_web.bat                   # Web launcher
│   └── README.txt                      # User guide
├── Pixelle-Video-v*-win64.zip          # ZIP package (version number varies)
└── Pixelle-Video-v*-win64.zip.sha256   # Checksum (version number varies)
```

## Build Process

The builder performs these steps:

1. **Download Phase**
   - Python embedded distribution
   - FFmpeg portable
   - Cached in `.cache/` for reuse

2. **Extract Phase**
   - Extract Python to `build/python/`
   - Extract FFmpeg to `build/tools/ffmpeg/`

3. **Prepare Phase**
   - Enable site-packages in Python
   - Install pip
   - Install uv (if configured)

4. **Install Phase**
   - Install project dependencies using uv/pip
   - Pre-install all packages

5. **Copy Phase**
   - Copy project files (excluding test/docs/cache)
   - Generate launcher scripts from templates
   - Create empty directories

6. **Package Phase**
   - Create ZIP archive
   - Generate SHA256 checksum

## Templates

Launcher script templates in `templates/`:

- `start.bat` - Main Web UI launcher
- `start_api.bat` - API server launcher  
- `start_web.bat` - Web UI only launcher
- `README.txt` - User documentation

Templates support placeholders:
- `{VERSION}` - Project version
- `{BUILD_DATE}` - Build timestamp

## Cache

Downloaded files are cached in `.cache/`:

```
.cache/
├── python-3.11.9-embed-amd64.zip
├── ffmpeg-6.1.1-win64.zip
└── get-pip.py
```

Delete cache to force re-download.

## Troubleshooting

### Build fails with "PyYAML not found"

```bash
pip install pyyaml
```

### Downloads are slow

Use China mirrors:

```bash
python build.py --cn-mirror
```

### Dependencies installation fails

Check:
1. Internet connection
2. PyPI mirrors accessibility
3. Project dependencies in `pyproject.toml`

### ZIP creation fails

Ensure:
1. Sufficient disk space
2. Write permissions to output directory
3. No files are locked by other processes

## Advanced Usage

### Custom Configuration

Create custom config file:

```bash
cp config/build_config.yaml config/my_config.yaml
# Edit my_config.yaml
python build.py --config config/my_config.yaml
```

### Skip ZIP Creation

Edit `build_config.yaml`:

```yaml
build:
  create_zip: false
```

### Include Chrome Portable

Edit `build_config.yaml`:

```yaml
chrome:
  include: true
  download_url: "https://path/to/chrome-portable.zip"
```

## Maintenance

### Update Python Version

Edit `config/build_config.yaml`:

```yaml
python:
  version: "3.11.10"
  download_url: "https://www.python.org/ftp/python/3.11.10/python-3.11.10-embed-amd64.zip"
```

### Update FFmpeg Version

Edit `config/build_config.yaml`:

```yaml
ffmpeg:
  version: "6.2.0"
  download_url: "https://github.com/BtbN/FFmpeg-Builds/releases/download/..."
```

## Distribution

To distribute the package:

1. Upload ZIP file to release page
2. Include SHA256 checksum for verification
3. Provide installation instructions

Users verify download:

```bash
# Windows PowerShell
Get-FileHash Pixelle-Video-v*-win64.zip -Algorithm SHA256
```

Compare with `.sha256` file.

## License

Same as Pixelle-Video project license.

