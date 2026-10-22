# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Template utility functions for size parsing and template management
"""

import os
from pathlib import Path
from typing import List, Tuple, Optional, Literal
from pydantic import BaseModel, Field
import logging

from pixelle_video.utils.os_util import (
    get_resource_path,
    list_resource_files,
    list_resource_dirs,
    resource_exists
)

logger = logging.getLogger(__name__)


def parse_template_size(template_path: str) -> Tuple[int, int]:
    """
    Parse video size from template path
    
    Args:
        template_path: Template path like "templates/1080x1920/default.html"
                      or "1080x1920/default.html"
    
    Returns:
        Tuple of (width, height) in pixels
    
    Raises:
        ValueError: If template path format is invalid
    
    Examples:
        >>> parse_template_size("templates/1080x1920/default.html")
        (1080, 1920)
        >>> parse_template_size("1920x1080/modern.html")
        (1920, 1080)
    """
    path = Path(template_path)
    
    # Get parent directory name (should be like "1080x1920")
    dir_name = path.parent.name
    
    # Special case: if parent is "templates", go up one more level
    if dir_name == "templates":
        # This shouldn't happen in new structure, but handle it
        raise ValueError(
            f"Invalid template path format: {template_path}. "
            f"Expected format: 'WIDTHxHEIGHT/template.html' or 'templates/WIDTHxHEIGHT/template.html'"
        )
    
    # Parse size from directory name
    if 'x' not in dir_name:
        raise ValueError(
            f"Invalid size format in path: {template_path}. "
            f"Directory name should be 'WIDTHxHEIGHT' (e.g., '1080x1920')"
        )
    
    try:
        width_str, height_str = dir_name.split('x')
        width = int(width_str)
        height = int(height_str)
        
        # Sanity check
        if width < 100 or height < 100 or width > 10000 or height > 10000:
            raise ValueError(f"Invalid size dimensions: {width}x{height}")
        
        return (width, height)
    except ValueError as e:
        raise ValueError(
            f"Failed to parse size from path: {template_path}. "
            f"Expected format: 'WIDTHxHEIGHT/template.html' (e.g., '1080x1920/default.html'). "
            f"Error: {e}"
        )


def list_available_sizes() -> List[str]:
    """
    List all available video sizes (merged from templates/ and data/templates/)
    
    Returns:
        List of size strings like ["1080x1920", "1920x1080", "1080x1080"]
    
    Examples:
        >>> list_available_sizes()
        ['1080x1920', '1920x1080', '1080x1080']
    """
    # Use new resource API to merge default and custom directories
    all_dirs = list_resource_dirs("templates")
    
    # Filter to only valid size formats (WIDTHxHEIGHT)
    sizes = []
    for dir_name in all_dirs:
        if 'x' in dir_name:
            try:
                width, height = dir_name.split('x')
                int(width)
                int(height)
                sizes.append(dir_name)
            except (ValueError, AttributeError):
                # Skip invalid directories
                continue
    
    return sorted(sizes)


def list_templates_for_size(size: str) -> List[str]:
    """
    List all templates available for a given size (merged from templates/ and data/templates/)
    
    Args:
        size: Size string like "1080x1920"
    
    Returns:
        List of template filenames (without path) like ["default.html", "modern.html"]
    
    Examples:
        >>> list_templates_for_size("1080x1920")
        ['cartoon.html', 'default.html', 'elegant.html', 'modern.html', ...]
    """
    # Use new resource API to merge default and custom templates
    all_files = list_resource_files("templates", size)
    
    # Filter to only HTML files
    templates = [f for f in all_files if f.endswith('.html')]
    
    return sorted(templates)


def get_template_full_path(size: str, template_name: str) -> str:
    """
    Get full template path from size and template name (checks data/templates/ first, then templates/)
    
    Args:
        size: Size string like "1080x1920"
        template_name: Template filename like "default.html"
    
    Returns:
        Full path like "templates/1080x1920/default.html" or "data/templates/1080x1920/default.html"
    
    Raises:
        FileNotFoundError: If template file doesn't exist in either location
    
    Examples:
        >>> get_template_full_path("1080x1920", "default.html")
        'templates/1080x1920/default.html'
    """
    # Use new resource API to search custom first, then default
    try:
        return get_resource_path("templates", size, template_name)
    except FileNotFoundError:
        available_templates = list_templates_for_size(size)
        raise FileNotFoundError(
            f"Template not found: {size}/{template_name}\n"
            f"Available templates for size {size}: {available_templates}"
        )


class TemplateDisplayInfo(BaseModel):
    """Template display information for UI layer"""
    
    name: str = Field(..., description="Template name without extension")
    size: str = Field(..., description="Size string like '1080x1920'")
    width: int = Field(..., description="Width in pixels")
    height: int = Field(..., description="Height in pixels")
    orientation: Literal['portrait', 'landscape', 'square'] = Field(
        ..., 
        description="Video orientation"
    )
    is_standard: bool = Field(
        ..., 
        description="True only for standard sizes: 1080x1920, 1920x1080, 1080x1080"
    )


class TemplateInfo(BaseModel):
    """Complete template information with path and display info"""
    
    template_path: str = Field(..., description="Full template path like '1080x1920/default.html'")
    display_info: TemplateDisplayInfo = Field(..., description="Display information")


def format_template_display_info(template_name: str, size: str) -> TemplateDisplayInfo:
    """
    Format template display information for UI
    
    Returns structured data for UI layer to handle display and i18n.
    
    Args:
        template_name: Template filename like "default.html"
        size: Size string like "1080x1920"
    
    Returns:
        TemplateDisplayInfo object with name, size, dimensions, orientation, and standard flag
    
    Examples:
        >>> info = format_template_display_info("default.html", "1080x1920")
        >>> info.name
        'default'
        >>> info.is_standard
        True
        
        >>> info = format_template_display_info("custom.html", "1080x1921")
        >>> info.orientation
        'portrait'
        >>> info.is_standard
        False
    """
    # Keep full template name with .html extension
    name = template_name
    
    # Parse size
    width, height = map(int, size.split('x'))
    
    # Detect orientation
    if height > width:
        orientation = 'portrait'
    elif width > height:
        orientation = 'landscape'
    else:
        orientation = 'square'
    
    # Check if it's a standard size (only these three)
    is_standard = (width, height) in [(1080, 1920), (1920, 1080), (1080, 1080)]
    
    return TemplateDisplayInfo(
        name=name,
        size=size,
        width=width,
        height=height,
        orientation=orientation,
        is_standard=is_standard
    )


def get_all_templates_with_info() -> List[TemplateInfo]:
    """
    Get all templates with their display information
    
    Returns:
        List of TemplateInfo objects
    
    Example:
        >>> templates = get_all_templates_with_info()
        >>> for t in templates:
        ...     print(f"{t.display_info.name} - {t.display_info.orientation}")
        ...     print(f"  Path: {t.template_path}")
        ...     print(f"  Standard: {t.display_info.is_standard}")
    """
    result = []
    sizes = list_available_sizes()
    
    for size in sizes:
        templates = list_templates_for_size(size)
        for template in templates:
            display_info = format_template_display_info(template, size)
            full_path = f"{size}/{template}"
            result.append(TemplateInfo(
                template_path=full_path,
                display_info=display_info
            ))
    
    return result


def get_templates_grouped_by_size() -> dict:
    """
    Get templates grouped by size
    
    Returns:
        Dict with size as key, list of TemplateInfo as value
        Ordered by orientation priority: portrait > landscape > square
    
    Example:
        >>> grouped = get_templates_grouped_by_size()
        >>> for size, templates in grouped.items():
        ...     print(f"Size: {size}")
        ...     for t in templates:
        ...         print(f"  - {t.display_info.name}")
    """
    from collections import defaultdict
    
    templates = get_all_templates_with_info()
    grouped = defaultdict(list)
    
    for t in templates:
        grouped[t.display_info.size].append(t)
    
    # Sort groups by orientation priority: portrait > landscape > square
    orientation_priority = {'portrait': 0, 'landscape': 1, 'square': 2}
    
    sorted_grouped = {}
    for size in sorted(grouped.keys(), key=lambda s: (
        orientation_priority.get(grouped[s][0].display_info.orientation, 3),
        s
    )):
        sorted_grouped[size] = sorted(grouped[size], key=lambda t: t.display_info.name)
    
    return sorted_grouped


def resolve_template_path(template_input: Optional[str]) -> str:
    """
    Resolve template input to full path with validation (checks data/templates/ first, then templates/)
    
    Args:
        template_input: Can be:
            - None: Use default "1080x1920/image_default.html"
            - "template.html": Use default size + this template
            - "1080x1920/template.html": Full relative path
            - "templates/1080x1920/template.html": Absolute-ish path (legacy)
            - "data/templates/1080x1920/template.html": Custom path (legacy)
    
    Returns:
        Resolved full path (custom if exists, otherwise default)
    
    Raises:
        FileNotFoundError: If template doesn't exist in either location
    
    Examples:
        >>> resolve_template_path(None)
        'templates/1080x1920/image_default.html'
        >>> resolve_template_path("image_modern.html")
        'templates/1080x1920/image_modern.html'
        >>> resolve_template_path("1920x1080/image_default.html")
        'templates/1920x1080/image_default.html'
    """
    # Default case
    if template_input is None:
        template_input = "1080x1920/image_default.html"
    
    # Parse input to extract size and template name
    size = None
    template_name = None
    
    # Handle different input formats
    if template_input.startswith("templates/") or template_input.startswith("data/templates/"):
        # Legacy full path format - extract size and name
        parts = Path(template_input).parts
        if len(parts) >= 3:
            size = parts[-2]
            template_name = parts[-1]
    elif '/' in template_input and 'x' in template_input.split('/')[0]:
        # "1080x1920/template.html" format
        size, template_name = template_input.split('/', 1)
    else:
        # Just template name - use default size
        size = "1080x1920"
        template_name = template_input
    
    # Backward compatibility: migrate "default.html" to "image_default.html"
    if template_name == "default.html":
        migrated_name = "image_default.html"
        try:
            # Try migrated name first
            path = get_resource_path("templates", size, migrated_name)
            logger.info(f"Backward compatibility: migrated '{template_input}' to '{size}/{migrated_name}'")
            return path
        except FileNotFoundError:
            # Fall through to try original name
            logger.warning(f"Migrated template '{size}/{migrated_name}' not found, trying original name")
    
    # Use resource API to resolve path (custom > default)
    try:
        return get_resource_path("templates", size, template_name)
    except FileNotFoundError:
        available_sizes = list_available_sizes()
        raise FileNotFoundError(
            f"Template not found: {size}/{template_name}\n"
            f"Available sizes: {available_sizes}\n"
            f"Hint: Use format 'SIZExSIZE/template.html' (e.g., '1080x1920/image_default.html')"
        )


def get_template_type(template_name: str) -> Literal['static', 'image', 'video']:
    """
    Detect template type from template filename
    
    Template naming convention:
    - static_*.html: Static style templates (no AI-generated media)
    - image_*.html: Templates requiring AI-generated images
    - video_*.html: Templates requiring AI-generated videos
    
    Args:
        template_name: Template filename like "image_default.html" or "video_simple.html"
    
    Returns:
        Template type: 'static', 'image', or 'video'
    
    Examples:
        >>> get_template_type("static_simple.html")
        'static'
        >>> get_template_type("image_default.html")
        'image'
        >>> get_template_type("video_simple.html")
        'video'
    """
    name = Path(template_name).name
    
    if name.startswith("static_"):
        return "static"
    elif name.startswith("video_"):
        return "video"
    elif name.startswith("image_"):
        return "image"
    else:
        # Fallback: try to detect from legacy names
        logger.warning(
            f"Template '{template_name}' doesn't follow naming convention (static_/image_/video_). "
            f"Defaulting to 'image' type."
        )
        return "image"


def filter_templates_by_type(
    templates: List[TemplateInfo], 
    template_type: Literal['static', 'image', 'video']
) -> List[TemplateInfo]:
    """
    Filter templates by type
    
    Args:
        templates: List of TemplateInfo objects
        template_type: Type to filter by ('static', 'image', or 'video')
    
    Returns:
        Filtered list of TemplateInfo objects
    
    Examples:
        >>> all_templates = get_all_templates_with_info()
        >>> image_templates = filter_templates_by_type(all_templates, 'image')
        >>> len(image_templates) > 0
        True
    """
    filtered = []
    for t in templates:
        template_name = t.display_info.name
        if get_template_type(template_name) == template_type:
            filtered.append(t)
    return filtered


def get_templates_grouped_by_size_and_type(
    template_type: Optional[Literal['static', 'image', 'video']] = None
) -> dict:
    """
    Get templates grouped by size, optionally filtered by type
    
    Args:
        template_type: Optional type filter ('static', 'image', or 'video')
    
    Returns:
        Dict with size as key, list of TemplateInfo as value
        Ordered by orientation priority: portrait > landscape > square
    
    Examples:
        >>> # Get all templates
        >>> all_grouped = get_templates_grouped_by_size_and_type()
        
        >>> # Get only image templates
        >>> image_grouped = get_templates_grouped_by_size_and_type('image')
    """
    from collections import defaultdict
    
    templates = get_all_templates_with_info()
    
    # Filter by type if specified
    if template_type is not None:
        templates = filter_templates_by_type(templates, template_type)
    
    grouped = defaultdict(list)
    
    for t in templates:
        grouped[t.display_info.size].append(t)
    
    # Sort groups by orientation priority: portrait > landscape > square
    orientation_priority = {'portrait': 0, 'landscape': 1, 'square': 2}
    
    sorted_grouped = {}
    for size in sorted(grouped.keys(), key=lambda s: (
        orientation_priority.get(grouped[s][0].display_info.orientation, 3),
        s
    )):
        sorted_grouped[size] = sorted(grouped[size], key=lambda t: t.display_info.name)
    
    return sorted_grouped

