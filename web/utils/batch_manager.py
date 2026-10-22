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
Lightweight batch manager for Streamlit (Simplified YAGNI version)
"""
import time
import traceback
from typing import List, Dict, Any, Optional, Callable
from loguru import logger


class SimpleBatchManager:
    """
    Ultra-simple batch manager following YAGNI principle
    
    Design principles:
    1. Only supports "AI generate content" mode
    2. Same config for all videos, only topics differ
    3. No CSV, no complex validation, just loop and execute
    """
    
    def __init__(self):
        self.results = []
        self.errors = []
        self.current_index = 0
        self.total_count = 0
    
    def execute_batch(
        self,
        pixelle_video,
        topics: List[str],
        shared_config: Dict[str, Any],
        overall_progress_callback: Optional[Callable] = None,
        task_progress_callback_factory: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Execute batch generation with shared config
        
        Args:
            pixelle_video: PixelleVideoCore instance
            topics: List of topics (one per video)
            shared_config: Shared configuration for all videos
            overall_progress_callback: Callback for overall progress
            task_progress_callback_factory: Factory function to create per-task callback
        
        Returns:
            {
                "results": [...],
                "errors": [...],
                "total_count": N,
                "success_count": M,
                "failed_count": K
            }
        """
        self.results = []
        self.errors = []
        self.total_count = len(topics)
        
        logger.info(f"Starting batch generation: {self.total_count} topics")
        
        for idx, topic in enumerate(topics, 1):
            self.current_index = idx
            
            # Report overall progress
            if overall_progress_callback:
                overall_progress_callback(
                    current=idx,
                    total=self.total_count,
                    topic=topic
                )
            
            try:
                logger.info(f"Task {idx}/{self.total_count} started: {topic}")
                
                # Extract title_prefix from shared_config (not a valid parameter for generate_video)
                title_prefix = shared_config.get("title_prefix")
                
                # Build task params (merge topic with shared config, excluding title_prefix)
                task_params = {
                    "text": topic,  # Topic as input
                    "mode": "generate",  # Fixed mode
                }
                
                # Merge shared config, excluding title_prefix and None values
                # Filter out None values to avoid interfering with parameter logic in generate_video
                for key, value in shared_config.items():
                    if key != "title_prefix" and value is not None:
                        task_params[key] = value
                
                # Generate title using title_prefix
                if title_prefix:
                    task_params["title"] = f"{title_prefix} - {topic}"
                else:
                    # Use topic as title
                    task_params["title"] = topic
                
                # Add per-task progress callback
                if task_progress_callback_factory:
                    task_params["progress_callback"] = task_progress_callback_factory(idx, topic)
                
                # Execute generation
                from web.utils.async_helpers import run_async
                result = run_async(pixelle_video.generate_video(**task_params))
                
                # Extract task_id from video_path (e.g., output/20251118_173821_f96a/final.mp4)
                from pathlib import Path
                task_id = Path(result.video_path).parent.name
                
                # Record success
                self.results.append({
                    "index": idx,
                    "topic": topic,
                    "task_id": task_id,
                    "video_path": result.video_path,
                    "status": "success"
                })
                
                logger.info(f"Task {idx}/{self.total_count} completed: {result.video_path}")
                
            except Exception as e:
                # Record error but continue
                error_msg = str(e)
                error_trace = traceback.format_exc()
                
                logger.error(f"Task {idx}/{self.total_count} failed: {error_msg}")
                logger.debug(f"Error traceback:\n{error_trace}")
                
                self.errors.append({
                    "index": idx,
                    "topic": topic,
                    "error": error_msg,
                    "traceback": error_trace,
                    "status": "failed"
                })
                
                # Continue to next task
                continue
        
        success_count = len(self.results)
        failed_count = len(self.errors)
        
        logger.info(
            f"Batch generation completed: "
            f"{success_count}/{self.total_count} succeeded, "
            f"{failed_count} failed"
        )
        
        return {
            "results": self.results,
            "errors": self.errors,
            "total_count": self.total_count,
            "success_count": success_count,
            "failed_count": failed_count
        }

