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
FastAPI Dependencies

Provides dependency injection for PixelleVideoCore and other services.
"""

from typing import Annotated
from fastapi import Depends
from loguru import logger

from pixelle_video.service import PixelleVideoCore


# Global Pixelle-Video instance
_pixelle_video_instance: PixelleVideoCore = None


async def get_pixelle_video() -> PixelleVideoCore:
    """
    Get Pixelle-Video core instance (dependency injection)
    
    Returns:
        PixelleVideoCore instance
    """
    global _pixelle_video_instance
    
    if _pixelle_video_instance is None:
        _pixelle_video_instance = PixelleVideoCore()
        await _pixelle_video_instance.initialize()
        logger.info("✅ Pixelle-Video initialized for API")
    
    return _pixelle_video_instance


async def shutdown_pixelle_video():
    """Shutdown Pixelle-Video instance and cleanup resources"""
    global _pixelle_video_instance
    if _pixelle_video_instance:
        logger.info("Shutting down Pixelle-Video...")
        await _pixelle_video_instance.cleanup()
        _pixelle_video_instance = None
    
    from pixelle_video.services.frame_html import HTMLFrameGenerator
    await HTMLFrameGenerator.close_browser()


# Type alias for dependency injection
PixelleVideoDep = Annotated[PixelleVideoCore, Depends(get_pixelle_video)]

