#!/usr/bin/env python3
"""
Windows Package Builder for Pixelle-Video

This script automates the creation of a Windows portable package:
1. Downloads Python embedded distribution
2. Downloads FFmpeg portable
3. Prepares Python environment (enable site-packages, install pip)
4. Installs project dependencies
5. Copies project files
6. Generates launcher scripts
7. Creates final ZIP package

Usage:
    python build.py [--config CONFIG] [--output OUTPUT] [--cn-mirror]
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.request import urlretrieve

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install it with: pip install pyyaml")
    sys.exit(1)


class Color:
    """ANSI color codes for terminal output"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


class WindowsPackageBuilder:
    """Build Windows portable package for Pixelle-Video"""
    
    def __init__(self, config_path: str, output_dir: Optional[str] = None, use_cn_mirror: bool = False):
        self.config_path = Path(config_path)
        self.script_dir = Path(__file__).parent
        self.project_root = self.script_dir.parent.parent
        
        # Load configuration
        with open(self.config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        # Override mirror setting if specified
        if use_cn_mirror:
            self.config['mirrors']['use_cn_mirror'] = True
        
        # Setup paths
        self.output_dir = Path(output_dir) if output_dir else self.project_root / self.config['build']['output_dir']
        self.cache_dir = self.project_root / self.config['cache']['cache_dir']
        self.templates_dir = self.script_dir / 'templates'
        
        # Get version from pyproject.toml
        self.version = self._read_version()
        self.package_name = f"{self.config['package']['name']}-v{self.version}-{self.config['package']['architecture']}"
        self.build_dir = self.output_dir / self.package_name
        
    def _read_version(self) -> str:
        """Read version from pyproject.toml"""
        pyproject_path = self.project_root / 'pyproject.toml'
        try:
            import tomllib
        except ImportError:
            # Python < 3.11 fallback
            try:
                import tomli as tomllib
            except ImportError:
                # Simple regex fallback
                import re
                with open(pyproject_path, 'r') as f:
                    content = f.read()
                    match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
                    if match:
                        return match.group(1)
                return "0.1.0"
        
        with open(pyproject_path, 'rb') as f:
            pyproject = tomllib.load(f)
            return pyproject.get('project', {}).get('version', '0.1.0')
    
    def log(self, message: str, level: str = "INFO"):
        """Print colored log message"""
        colors = {
            "INFO": Color.BLUE,
            "SUCCESS": Color.GREEN,
            "WARNING": Color.YELLOW,
            "ERROR": Color.RED,
            "HEADER": Color.HEADER,
        }
        color = colors.get(level, Color.RESET)
        print(f"{color}[{level}]{Color.RESET} {message}")
    
    def download_file(self, url: str, output_path: Path, description: str = "", max_retries: int = 3) -> bool:
        """Download file with progress indication and retry support"""
        import ssl
        import urllib.request
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    self.log(f"Retry {attempt}/{max_retries}...")
                
                self.log(f"Downloading {description or url}...")
                
                # Create SSL context that's more lenient
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                
                def report_progress(block_num, block_size, total_size):
                    downloaded = block_num * block_size
                    percent = min(downloaded / total_size * 100, 100) if total_size > 0 else 0
                    print(f"\r  Progress: {percent:.1f}%", end='', flush=True)
                
                # Try with urllib first
                opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_context))
                urllib.request.install_opener(opener)
                urlretrieve(url, output_path, reporthook=report_progress)
                print()  # New line after progress
                self.log(f"Downloaded to {output_path}", "SUCCESS")
                return True
                
            except Exception as e:
                self.log(f"Download attempt {attempt + 1} failed: {e}", "WARNING")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2)  # Wait before retry
                else:
                    self.log(f"All download attempts failed", "ERROR")
                    # Try with curl as fallback
                    return self._download_with_curl(url, output_path, description)
        
        return False
    
    def _find_suitable_python(self) -> Optional[str]:
        """Find a suitable Python 3.11+ for installing dependencies"""
        candidates = [
            # Try common locations for newer Python versions
            str(Path.home() / "miniforge3" / "bin" / "python3"),  # 当前用户的 Conda 路径
            '/opt/homebrew/bin/python3',           # Homebrew
            '/usr/local/bin/python3',              # Manual install
        ]
        
        # Also check what's in PATH
        for i in range(11, 14):  # Python 3.11, 3.12, 3.13
            for py_name in [f'python3.{i}', f'python{i}']:
                found = shutil.which(py_name)
                if found and found not in candidates:
                    candidates.append(found)
        
        # Check generic python3
        python3_path = shutil.which('python3')
        if python3_path and '.venv' not in python3_path:
            candidates.append(python3_path)
        
        # Test each candidate
        for candidate in candidates:
            try:
                if not candidate:
                    continue
                    
                # Skip if in project venv
                if '.venv' in candidate or 'venv' in candidate:
                    continue
                
                # Check if path exists
                if not os.path.exists(candidate):
                    continue
                
                # Check Python version
                result = subprocess.run(
                    [candidate, '-c', 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0:
                    version = result.stdout.strip()
                    major, minor = map(int, version.split('.'))
                    
                    # Need Python 3.11+
                    if major == 3 and minor >= 11:
                        # Check if pip is available
                        pip_check = subprocess.run(
                            [candidate, '-m', 'pip', '--version'],
                            capture_output=True,
                            timeout=5
                        )
                        if pip_check.returncode == 0:
                            self.log(f"Found Python {version} at {candidate}", "SUCCESS")
                            return candidate
            except Exception as e:
                continue
        
        return None
    
    def _download_with_curl(self, url: str, output_path: Path, description: str = "") -> bool:
        """Fallback download method using curl"""
        try:
            self.log(f"Trying curl fallback for {description}...")
            result = subprocess.run(
                ['curl', '-L', '-o', str(output_path), url, '--progress-bar'],
                check=True,
                capture_output=False
            )
            if result.returncode == 0 and output_path.exists():
                self.log(f"Downloaded with curl to {output_path}", "SUCCESS")
                return True
        except Exception as e:
            self.log(f"Curl download also failed: {e}", "ERROR")
        return False
    
    def download_python(self) -> Path:
        """Download Python embedded distribution"""
        python_config = self.config['python']
        cache_file = self.cache_dir / f"python-{python_config['version']}-embed-amd64.zip"
        
        if cache_file.exists():
            self.log(f"Using cached Python: {cache_file}")
            return cache_file
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Choose URL based on mirror setting
        url = python_config['mirror_url'] if self.config['mirrors']['use_cn_mirror'] else python_config['download_url']
        
        if self.download_file(url, cache_file, f"Python {python_config['version']}"):
            return cache_file
        else:
            raise RuntimeError("Failed to download Python")
    
    def download_ffmpeg(self) -> Path:
        """Download FFmpeg portable"""
        ffmpeg_config = self.config['ffmpeg']
        cache_file = self.cache_dir / f"ffmpeg-{ffmpeg_config['version']}-win64.zip"
        
        if cache_file.exists():
            self.log(f"Using cached FFmpeg: {cache_file}")
            return cache_file
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        url = ffmpeg_config['mirror_url'] if self.config['mirrors']['use_cn_mirror'] else ffmpeg_config['download_url']
        
        if self.download_file(url, cache_file, f"FFmpeg {ffmpeg_config['version']}"):
            return cache_file
        else:
            raise RuntimeError("Failed to download FFmpeg")
    
    def extract_python(self, zip_path: Path, target_dir: Path):
        """Extract Python embedded distribution"""
        self.log(f"Extracting Python to {target_dir}...")
        target_dir.mkdir(parents=True, exist_ok=True)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(target_dir)
        
        # Add execute permissions to .exe files (needed on Unix systems)
        if os.name != 'nt':  # Not on Windows
            for exe_file in target_dir.glob('*.exe'):
                os.chmod(exe_file, 0o755)
            for exe_file in target_dir.glob('**/*.exe'):
                os.chmod(exe_file, 0o755)
        
        self.log("Python extracted successfully", "SUCCESS")
    
    def extract_ffmpeg(self, zip_path: Path, target_dir: Path):
        """Extract FFmpeg portable"""
        self.log(f"Extracting FFmpeg to {target_dir}...")
        temp_extract = target_dir.parent / "ffmpeg_temp"
        temp_extract.mkdir(parents=True, exist_ok=True)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_extract)
        
        # Find the bin directory (FFmpeg archive has nested structure)
        bin_dir = None
        for root, dirs, files in os.walk(temp_extract):
            if 'bin' in dirs:
                bin_dir = Path(root) / 'bin'
                break
        
        if bin_dir and bin_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(bin_dir, target_dir, dirs_exist_ok=True)
            shutil.rmtree(temp_extract)
            self.log("FFmpeg extracted successfully", "SUCCESS")
        else:
            raise RuntimeError("FFmpeg bin directory not found in archive")
    
    def prepare_python_environment(self, python_dir: Path):
        """Prepare Python environment: enable site-packages"""
        self.log("Preparing Python environment...")
        
        # Modify python311._pth to enable site-packages
        pth_file = python_dir / "python311._pth"
        if pth_file.exists():
            with open(pth_file, 'r') as f:
                lines = f.readlines()
            
            # Uncomment "import site" line or add it
            modified = False
            for i, line in enumerate(lines):
                if line.strip().startswith('#import site'):
                    lines[i] = 'import site\n'
                    modified = True
                    break
            
            if not modified and 'import site' not in ''.join(lines):
                lines.append('import site\n')
            
            with open(pth_file, 'w') as f:
                f.writelines(lines)
            
            self.log("Enabled site-packages in Python", "SUCCESS")
        
        # Note: On non-Windows systems, we can't run python.exe directly
        # Pip and dependencies will be installed using system Python
        if os.name == 'nt':
            # On Windows, we can install pip directly
            python_exe = python_dir / "python.exe"
            get_pip_path = self.cache_dir / "get-pip.py"
            
            if not get_pip_path.exists():
                self.log("Downloading get-pip.py...")
                pip_url = "https://bootstrap.pypa.io/get-pip.py"
                self.download_file(pip_url, get_pip_path, "get-pip.py")
            
            self.log("Installing pip...")
            result = subprocess.run(
                [str(python_exe), str(get_pip_path)],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.log("Pip installed successfully", "SUCCESS")
            else:
                self.log(f"Pip installation warning: {result.stderr}", "WARNING")
        else:
            self.log("Cross-platform build detected (building on non-Windows)", "INFO")
            self.log("Dependencies will be installed using system Python", "INFO")
    
    def install_dependencies(self, python_dir: Path):
        """Install project dependencies"""
        self.log("Installing project dependencies...")
        
        # Determine target directory for site-packages
        site_packages = python_dir / "Lib" / "site-packages"
        site_packages.mkdir(parents=True, exist_ok=True)
        
        if os.name == 'nt':
            # On Windows, use the embedded Python
            python_exe = python_dir / "python.exe"
            
            # Install uv first if configured
            if self.config['build'].get('use_uv', True):
                self.log("Installing uv...")
                subprocess.run(
                    [str(python_exe), "-m", "pip", "install", "uv"],
                    check=True
                )
            
            # Install dependencies
            if self.config['build'].get('use_uv', True):
                cmd = [str(python_exe), "-m", "uv", "pip", "install", "-e", str(self.project_root)]
                if self.config['mirrors']['use_cn_mirror']:
                    cmd.extend(["--index-url", self.config['mirrors']['pypi_mirror']])
            else:
                cmd = [str(python_exe), "-m", "pip", "install", "-e", str(self.project_root)]
                if self.config['mirrors']['use_cn_mirror']:
                    cmd.extend(["--index-url", self.config['mirrors']['pypi_mirror']])
            
            self.log(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                self.log("Dependencies installed successfully", "SUCCESS")
            else:
                self.log(f"Dependency installation failed:\n{result.stderr}", "ERROR")
                raise RuntimeError("Failed to install dependencies")
        else:
            # Cross-platform build: use system Python to install to target directory
            self.log("Cross-platform build: using system Python to install dependencies")
            
            # Find a Python 3.11+ executable (not from project venv)
            python_cmd = self._find_suitable_python()
            
            if not python_cmd:
                self.log("No suitable Python 3.11+ found. Please install Python 3.11+ or use Windows to build.", "ERROR")
                raise RuntimeError("Python 3.11+ required for cross-platform build")
            
            self.log(f"Using Python: {python_cmd}")
            
            # Use pip with --target to install to specific directory
            cmd = [
                python_cmd, "-m", "pip", "install",
                "--target", str(site_packages),
                "--no-user",
                "--no-warn-script-location"
            ]
            
            # Read dependencies from pyproject.toml
            try:
                import tomllib
            except ImportError:
                try:
                    import tomli as tomllib
                except ImportError:
                    self.log("tomllib/tomli not available, trying simple parsing", "WARNING")
                    tomllib = None
            
            if tomllib:
                pyproject_path = self.project_root / "pyproject.toml"
                with open(pyproject_path, 'rb') as f:
                    pyproject = tomllib.load(f)
                    deps = pyproject.get('project', {}).get('dependencies', [])
            else:
                # Simple fallback: read from pyproject.toml manually
                import re
                pyproject_path = self.project_root / "pyproject.toml"
                with open(pyproject_path, 'r') as f:
                    content = f.read()
                    # Find dependencies section
                    deps_match = re.search(r'dependencies\s*=\s*\[(.*?)\]', content, re.DOTALL)
                    if deps_match:
                        deps_str = deps_match.group(1)
                        deps = [dep.strip(' "\',\n') for dep in deps_str.split('\n') if dep.strip() and not dep.strip().startswith('#')]
                    else:
                        deps = []
            
            if deps:
                cmd.extend(deps)
                
                if self.config['mirrors']['use_cn_mirror']:
                    cmd.extend(["--index-url", self.config['mirrors']['pypi_mirror']])
                
                self.log(f"Installing {len(deps)} dependencies...")
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode == 0:
                    self.log("Dependencies installed successfully", "SUCCESS")
                else:
                    self.log(f"Dependency installation output:\n{result.stdout}", "INFO")
                    if result.stderr:
                        self.log(f"Warnings: {result.stderr}", "WARNING")
            else:
                self.log("No dependencies found in pyproject.toml", "WARNING")
    
    def copy_project_files(self, target_dir: Path):
        """Copy project files to build directory"""
        self.log(f"Copying project files to {target_dir}...")
        
        exclude_patterns = self.config['build']['exclude_patterns']
        
        def should_exclude(path: Path) -> bool:
            path_str = str(path.relative_to(self.project_root))
            for pattern in exclude_patterns:
                if pattern.endswith('/*'):
                    # Directory content exclusion - must match exact directory name or start with "dirname/"
                    dir_name = pattern[:-2]
                    if path_str == dir_name or path_str.startswith(f"{dir_name}/"):
                        return True
                elif pattern.endswith('*'):
                    # Wildcard pattern
                    if path_str.startswith(pattern[:-1]):
                        return True
                elif '*' in pattern:
                    # Glob pattern (simple check)
                    import fnmatch
                    if fnmatch.fnmatch(path_str, pattern):
                        return True
                else:
                    # Exact match or directory
                    if path_str == pattern or path_str.startswith(f"{pattern}/"):
                        return True
            return False
        
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy files
        copied_count = 0
        for item in self.project_root.iterdir():
            if item.name in ['.git', 'packaging', 'dist', '.venv', 'venv']:
                continue
            
            if should_exclude(item):
                continue
            
            target_path = target_dir / item.name
            
            if item.is_file():
                shutil.copy2(item, target_path)
                copied_count += 1
            elif item.is_dir():
                shutil.copytree(item, target_path, ignore=lambda d, names: [
                    n for n in names if should_exclude(Path(d) / n)
                ])
                # Count files in copied directory
                copied_count += sum(1 for _ in target_path.rglob('*') if _.is_file())
        
        self.log(f"Copied {copied_count} files", "SUCCESS")
    
    def generate_launcher_scripts(self):
        """Generate launcher scripts from templates"""
        self.log("Generating launcher scripts...")
        
        replacements = {
            '{VERSION}': self.version,
            '{BUILD_DATE}': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        # Copy and process templates
        for template_file in self.templates_dir.glob('*'):
            if template_file.is_file():
                target_file = self.build_dir / template_file.name
                
                with open(template_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Replace placeholders
                for key, value in replacements.items():
                    content = content.replace(key, value)
                
                with open(target_file, 'w', encoding='utf-8', newline='\r\n') as f:
                    f.write(content)
                
                self.log(f"Generated: {template_file.name}")
        
        self.log("Launcher scripts generated", "SUCCESS")
    
    def create_empty_directories(self):
        """Create empty directories specified in config"""
        self.log("Creating empty directories...")
        
        for dir_name in self.config['build'].get('create_empty_dirs', []):
            dir_path = self.build_dir / dir_name
            dir_path.mkdir(parents=True, exist_ok=True)
            # Create .gitkeep to preserve directory in git
            (dir_path / '.gitkeep').touch()
        
        self.log("Empty directories created", "SUCCESS")
    
    def create_zip_package(self):
        """Create final ZIP package"""
        if not self.config['build'].get('create_zip', True):
            return
        
        zip_path = self.output_dir / f"{self.package_name}.zip"
        self.log(f"Creating ZIP package: {zip_path}...")
        
        compression_map = {
            'deflate': zipfile.ZIP_DEFLATED,
            'bzip2': zipfile.ZIP_BZIP2,
            'lzma': zipfile.ZIP_LZMA,
        }
        compression = compression_map.get(
            self.config['build'].get('zip_compression', 'deflate'),
            zipfile.ZIP_DEFLATED
        )
        
        with zipfile.ZipFile(zip_path, 'w', compression) as zipf:
            for root, dirs, files in os.walk(self.build_dir):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(self.build_dir.parent)
                    zipf.write(file_path, arcname)
        
        # Calculate file size and hash
        size_mb = zip_path.stat().st_size / (1024 * 1024)
        
        with open(zip_path, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        
        self.log(f"ZIP package created: {zip_path}", "SUCCESS")
        self.log(f"Size: {size_mb:.2f} MB")
        self.log(f"SHA256: {file_hash}")
        
        # Write hash to file
        hash_file = zip_path.with_suffix('.zip.sha256')
        with open(hash_file, 'w') as f:
            f.write(f"{file_hash}  {zip_path.name}\n")
    
    def build(self):
        """Main build process"""
        self.log("=" * 60, "HEADER")
        self.log(f"Building {self.package_name}", "HEADER")
        self.log("=" * 60, "HEADER")
        
        try:
            # Clean build directory
            if self.build_dir.exists():
                self.log(f"Cleaning existing build directory: {self.build_dir}")
                shutil.rmtree(self.build_dir)
            
            self.build_dir.mkdir(parents=True, exist_ok=True)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            
            # Download dependencies
            python_zip = self.download_python()
            ffmpeg_zip = self.download_ffmpeg()
            
            # Extract Python
            python_dir = self.build_dir / "python" / "python311"
            self.extract_python(python_zip, python_dir)
            
            # Extract FFmpeg
            ffmpeg_dir = self.build_dir / "tools" / "ffmpeg" / "bin"
            self.extract_ffmpeg(ffmpeg_zip, ffmpeg_dir)
            
            # Prepare Python environment
            self.prepare_python_environment(python_dir)
            
            # Install dependencies
            if self.config['build'].get('pre_install_deps', True):
                self.install_dependencies(python_dir)
            
            # Copy project files
            project_target = self.build_dir / "Pixelle-Video"
            self.copy_project_files(project_target)
            
            # Generate launcher scripts
            self.generate_launcher_scripts()
            
            # Create empty directories
            self.create_empty_directories()
            
            # Create ZIP package
            self.create_zip_package()
            
            self.log("=" * 60, "HEADER")
            self.log("Build completed successfully!", "SUCCESS")
            self.log(f"Package location: {self.build_dir}", "SUCCESS")
            self.log("=" * 60, "HEADER")
            
        except Exception as e:
            self.log(f"Build failed: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Build Windows portable package for Pixelle-Video")
    parser.add_argument(
        '--config',
        default='packaging/windows/config/build_config.yaml',
        help='Path to build configuration file'
    )
    parser.add_argument(
        '--output',
        help='Output directory (default: dist/windows)'
    )
    parser.add_argument(
        '--cn-mirror',
        action='store_true',
        help='Use China mirrors for faster downloads'
    )
    
    args = parser.parse_args()
    
    builder = WindowsPackageBuilder(
        config_path=args.config,
        output_dir=args.output,
        use_cn_mirror=args.cn_mirror
    )
    builder.build()


if __name__ == '__main__':
    main()

