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
Base Pipeline for Video Generation

All custom pipelines should inherit from BasePipeline.
"""

from abc import ABC, abstractmethod
from typing import Optional, Callable

from loguru import logger

from pixelle_video.models.progress import ProgressEvent
from pixelle_video.models.storyboard import VideoGenerationResult


class BasePipeline(ABC):
    """
    Base pipeline for video generation
    
    All custom pipelines should inherit from this class and implement __call__.
    
    Design principles:
    - Each pipeline represents a complete video generation workflow
    - Pipelines are independent and can have completely different logic
    - Pipelines have access to all core services via self.core
    - Pipelines should report progress via progress_callback
    
    Example:
        >>> class MyPipeline(BasePipeline):
        ...     async def __call__(self, text: str, **kwargs):
        ...         # Step 1: Generate content
        ...         narrations = await some_logic(text)
        ...         
        ...         # Step 2: Process frames
        ...         for narration in narrations:
        ...             audio = await self.core.tts(narration)
        ...             # ...
        ...         
        ...         return VideoGenerationResult(...)
    """
    
    def __init__(self, pixelle_video_core):
        """
        Initialize pipeline with core services
        
        Args:
            pixelle_video_core: PixelleVideoCore instance (provides access to all services)
        """
        self.core = pixelle_video_core
        
        # Quick access to services (convenience)
        self.llm = pixelle_video_core.llm
        self.tts = pixelle_video_core.tts
        self.media = pixelle_video_core.media
        self.video = pixelle_video_core.video
        
        # Backward compatibility alias
        self.image = pixelle_video_core.media
    
    @abstractmethod
    async def __call__(
        self,
        text: str,
        progress_callback: Optional[Callable[[ProgressEvent], None]] = None,
        **kwargs
    ) -> VideoGenerationResult:
        """
        Execute the pipeline
        
        Args:
            text: Input text (meaning varies by pipeline)
            progress_callback: Optional callback for progress updates (receives ProgressEvent)
            **kwargs: Pipeline-specific parameters
            
        Returns:
            VideoGenerationResult with video path and metadata
            
        Raises:
            Exception: Pipeline-specific exceptions
        """
        pass
    
    def _report_progress(
        self,
        callback: Optional[Callable[[ProgressEvent], None]],
        event_type: str,
        progress: float,
        **kwargs
    ):
        """
        Report progress via callback
        
        Args:
            callback: Progress callback function
            event_type: Type of progress event
            progress: Progress value (0.0-1.0)
            **kwargs: Additional event-specific parameters (frame_current, frame_total, etc.)
        """
        if callback:
            event = ProgressEvent(event_type=event_type, progress=progress, **kwargs)
            callback(event)
            logger.debug(f"Progress: {progress*100:.0f}% - {event_type}")
        else:
            logger.debug(f"Progress: {progress*100:.0f}% - {event_type}")

