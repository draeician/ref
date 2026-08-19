"""
YouTube Transcript API with Metadata

This module provides functions to fetch YouTube video transcripts and metadata,
returning structured JSON data that includes the complete transcript text,
video duration, and video metadata (title, channel, published date).

ASSUMPTION: English language transcripts only. The API will fetch the primary
transcript which is typically English for English-language videos.

Compatibility note:
    youtube-transcript-api >= 1.2.0 changed ``YouTubeTranscriptApi.fetch()`` to
    return a ``FetchedTranscript`` object (iterable of ``FetchedTranscriptSnippet``
    dataclasses) instead of a plain ``list[dict]``. All segment access in this
    module goes through ``_get_segment_field`` so it works against both shapes.

Example JSON Output:
{
  "transcript": "Complete video transcript text...",
  "duration": 1234,
  "comments": [],
  "metadata": {
    "id": "dQw4w9WgXcQ",
    "title": "Rick Astley - Never Gonna Give You Up (Official Video)",
    "channel": "Rick Astley",
    "published_at": "2009-10-25T06:57:33Z"
  }
}

Requirements:
- youtube-transcript-api
- google-api-python-client (for metadata)
- YouTube Data API v3 key (optional, for full metadata)

Usage:
    # Basic usage (no API key required for transcript)
    result = get_youtube_transcript_with_metadata('dQw4w9WgXcQ')

    # With API key for full metadata
    result = get_youtube_transcript_with_metadata('dQw4w9WgXcQ', api_key='your_key')

    # Using environment variable
    export YOUTUBE_API_KEY='your_key_here'
    result = get_youtube_transcript_with_metadata('dQw4w9WgXcQ')
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, NoReturn, Optional

from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi

try:
    # youtube-transcript-api >= 1.2.0 re-exports exceptions at the package root.
    from youtube_transcript_api import RequestBlocked
except ImportError:  # pragma: no cover - older versions expose them privately.
    from youtube_transcript_api._errors import RequestBlocked

# You'll need to set your YouTube Data API key as an environment variable
# Get your API key from: https://console.developers.google.com/
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

BLOCKED_ERROR_GUIDANCE_URL = (
    "https://github.com/jdepoix/youtube-transcript-api"
    "?tab=readme-ov-file#working-around-ip-bans-requestblocked-or-ipblocked-exception"
)

BLOCKED_ERROR_USER_MESSAGE = (
    "YouTube is blocking transcript requests from your IP address. "
    f"See {BLOCKED_ERROR_GUIDANCE_URL} for steps to restore access."
)


def _is_request_blocked_error(error: Exception) -> bool:
    """Return True if the error message indicates a YouTube IP block.

    Used as a fallback when a blocked error is not raised as a ``RequestBlocked``
    instance (e.g. a subclass with a different name, or an older library version
    that surfaces the block via a plain message string).
    """
    message = str(error).lower()
    indicators = [
        "youtube is blocking requests from your ip",
        "youtube is blocking requests from your ip address",
        "requests from your ip have been blocked",
        "requestblocked",
        "ipblocked",
    ]
    return any(phrase in message for phrase in indicators)


def _get_segment_field(segment: Any, field_name: str, default: Any = None) -> Any:
    """Read a transcript snippet field across youtube-transcript-api versions.

    In v1.2.0+ ``fetch()`` yields ``FetchedTranscriptSnippet`` dataclass objects,
    so fields are read as attributes (``segment.text``, ``segment.duration``).
    Earlier releases yielded plain ``dict`` objects read as keys
    (``segment['text']``, ``segment['duration']``). This helper supports both,
    so neither a ``TypeError`` ("object is not subscriptable") nor a
    ``KeyError`` can be raised when accessing a snippet field.
    """
    if isinstance(segment, dict):
        return segment.get(field_name, default)
    return getattr(segment, field_name, default)


def _extract_transcript(fetched_transcript: Any) -> tuple[str, float]:
    """Join transcript segments into text and sum their durations.

    Accepts either a ``FetchedTranscript`` (iterable of
    ``FetchedTranscriptSnippet`` objects, youtube-transcript-api >= 1.2.0) or
    the older list-of-dicts shape.

    Returns:
        tuple[str, float]: ``(complete_text, total_duration_seconds)``.
    """
    text_segments: List[str] = []
    total_duration = 0.0

    for segment in fetched_transcript:
        text_segments.append(_get_segment_field(segment, "text", "") or "")
        total_duration += float(_get_segment_field(segment, "duration", 0.0) or 0.0)

    return " ".join(text_segments), total_duration


def _raise_request_blocked(original: Exception) -> NoReturn:
    """Re-raise a blocked-transcript error with the user-facing guidance message.

    Maintained from the original exception handling. ``RequestBlocked`` is passed
    the guidance string so ``str(exc)`` always contains both "blocking transcript
    requests" and the official workaround URL. This is safe across versions:
    youtube-transcript-api < 1.2.0 builds the exception from a message string,
    while >= 1.2.0 treats the argument as a ``video_id`` and renders its own
    detailed cause (which still embeds this guidance text). The original error is
    preserved as ``__cause__`` via ``raise ... from original``.
    """
    raise RequestBlocked(BLOCKED_ERROR_USER_MESSAGE) from original


def get_youtube_transcript_with_metadata(video_id: str, api_key: Optional[str] = None, save_to_file: bool = True) -> Dict[str, Any]:
    """
    Fetches the English transcript and metadata for a YouTube video and returns a structured JSON.
    Also saves the output to <videoid>.json in the current working directory.

    Note: This function assumes English-language transcripts only and will fetch the primary
    transcript available for the video.

    Args:
        video_id (str): The YouTube video ID (e.g., 'J9coELhl-EQ')
        api_key (str, optional): YouTube Data API key. If not provided, will use YOUTUBE_API_KEY env var
        save_to_file (bool, optional): Whether to save JSON to file. Defaults to True.

    Returns:
        Dict[str, Any]: A dictionary containing:
            - transcript: The complete English transcript text
            - duration: Total duration in seconds (rounded to the nearest integer)
            - comments: Empty array (placeholder)
            - metadata: Video metadata (id, title, channel, published_at)

    Raises:
        Exception: If transcript or metadata cannot be fetched or file cannot be written
    """
    try:
        # Fetch the transcript. v1.2.0+ returns a FetchedTranscript; older
        # versions return a list of dicts. Both are iterable of segments.
        api = YouTubeTranscriptApi()
        fetched_transcript = api.fetch(video_id)

        # Extract text and total duration in a version-agnostic way.
        complete_text, total_duration = _extract_transcript(fetched_transcript)

        # Fetch video metadata using YouTube Data API
        metadata = get_video_metadata(video_id, api_key or YOUTUBE_API_KEY)

        # Construct the JSON response. Duration is rounded (not truncated) to
        # the nearest whole second for accuracy.
        result = {
            "transcript": complete_text,
            "duration": round(total_duration),
            "comments": [],
            "metadata": metadata
        }

        # Save to file if requested
        if save_to_file:
            filename = f"{video_id}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(f"✓ Transcript saved to: {filename}")

        return result

    except RequestBlocked as e:
        _raise_request_blocked(e)
    except Exception as e:
        # Check if it's a transcript unavailable error
        error_msg = str(e).lower()
        if _is_request_blocked_error(e):
            _raise_request_blocked(e)
        if any(phrase in error_msg for phrase in [
            'could not retrieve a transcript',
            'subtitles are disabled',
            'no transcript',
            'transcript not available',
            'no subtitles'
        ]):
            # This is a normal case for videos without transcripts (like music videos)
            raise Exception(f"No transcript available for video {video_id}: {str(e)}") from e
        else:
            # This is an unexpected error
            raise Exception(f"Failed to fetch transcript and metadata for video {video_id}: {str(e)}") from e


def get_video_metadata(video_id: str, api_key: Optional[str]) -> Dict[str, str]:
    """
    Fetches video metadata using YouTube Data API v3.

    Args:
        video_id (str): YouTube video ID
        api_key (str): YouTube Data API key (may be None)

    Returns:
        Dict[str, str]: Video metadata dictionary. The schema is stable: every
        return path (success, missing API key, and API failure) returns exactly
        the keys ``id``, ``title``, ``channel``, and ``published_at``, so
        downstream JSON validators never hit a missing-key error.
    """
    if not api_key:
        # Return minimal metadata if no API key is provided
        return {
            "id": video_id,
            "title": "Title unavailable (no API key)",
            "channel": "Channel unavailable (no API key)",
            "published_at": "Date unavailable (no API key)"
        }

    try:
        youtube = build('youtube', 'v3', developerKey=api_key)

        request = youtube.videos().list(
            part='snippet',
            id=video_id
        )

        response = request.execute()

        if not response.get('items'):
            raise ValueError(f"Video {video_id} not found")

        video_info = response['items'][0]['snippet']

        # Use .get() with stable defaults so a missing snippet field still
        # yields the full four-key schema rather than raising a KeyError.
        return {
            "id": video_id,
            "title": video_info.get('title', 'Title unavailable'),
            "channel": video_info.get('channelTitle', 'Channel unavailable'),
            "published_at": video_info.get('publishedAt', 'Date unavailable')
        }

    except Exception as e:
        # Fallback metadata if API call fails. Same four-key schema as above.
        return {
            "id": video_id,
            "title": f"Title unavailable ({str(e)})",
            "channel": f"Channel unavailable ({str(e)})",
            "published_at": f"Date unavailable ({str(e)})"
        }


def get_youtube_transcript(video_id: str) -> tuple[str, float]:
    """
    Original function maintained for backward compatibility.
    Fetches the transcript for a YouTube video and combines all text segments
    while calculating the total duration.

    Args:
        video_id (str): The YouTube video ID (e.g., 'J9coELhl-EQ')

    Returns:
        Tuple[str, float]: A tuple containing:
            - The complete transcript text as a single string
            - The total duration of the video in seconds

    Raises:
        Exception: If transcript cannot be fetched or processed
    """
    try:
        # Fetch the transcript. v1.2.0+ returns a FetchedTranscript; older
        # versions return a list of dicts. Both are iterable of segments.
        api = YouTubeTranscriptApi()
        fetched_transcript = api.fetch(video_id)

        return _extract_transcript(fetched_transcript)

    except Exception as e:
        raise Exception(f"Failed to fetch transcript for video {video_id}: {str(e)}") from e


def get_youtube_transcript_with_languages(video_id: str, languages: Optional[list] = None) -> tuple[str, float]:
    """
    Fetches the transcript for a YouTube video with language preference support.

    Args:
        video_id (str): The YouTube video ID
        languages (list, optional): List of language codes to try (e.g., ['en', 'es'])

    Returns:
        Tuple[str, float]: A tuple containing the complete transcript text and total duration
    """
    try:
        # Fetch the transcript with optional language preference. The ``languages``
        # keyword is supported by youtube-transcript-api 1.2.0+.
        api = YouTubeTranscriptApi()
        if languages:
            fetched_transcript = api.fetch(video_id, languages=languages)
        else:
            fetched_transcript = api.fetch(video_id)

        return _extract_transcript(fetched_transcript)

    except Exception as e:
        raise Exception(f"Failed to fetch transcript for video {video_id}: {str(e)}") from e


# Example usage
if __name__ == "__main__":
    # Example with the video ID from the original comment
    video_id = "J9coELhl-EQ"

    print("=" * 60)
    print("FETCHING YOUTUBE TRANSCRIPT WITH METADATA")
    print("=" * 60)

    try:
        # Test the new function with metadata (saves to file by default)
        result = get_youtube_transcript_with_metadata(video_id)

        print(f"\nSummary:")
        print(f"✓ Video ID: {result['metadata']['id']}")
        print(f"✓ Title: {result['metadata']['title']}")
        print(f"✓ Channel: {result['metadata']['channel']}")
        print(f"✓ Published: {result['metadata']['published_at']}")
        print(f"✓ Duration: {result['duration']} seconds ({result['duration']//60}:{result['duration']%60:02d})")
        print(f"✓ Transcript length: {len(result['transcript'])} characters")
        print(f"✓ Word count: {len(result['transcript'].split())} words")
        print(f"✓ File saved: {video_id}.json")

    except Exception as e:
        print(f"Error: {e}")

    print("\n" + "=" * 60)
    print("USAGE EXAMPLES")
    print("=" * 60)
    print("# Save to file (default behavior)")
    print("result = get_youtube_transcript_with_metadata('UbDyjIIGaxQ')")
    print()
    print("# Don't save to file, just return data")
    print("result = get_youtube_transcript_with_metadata('UbDyjIIGaxQ', save_to_file=False)")
    print()
    print("# With API key for full metadata")
    print("result = get_youtube_transcript_with_metadata('UbDyjIIGaxQ', api_key='your_key')")

    print("\n" + "=" * 60)
    print("API KEY SETUP")
    print("=" * 60)
    print("1. For full metadata, set YOUTUBE_API_KEY environment variable")
    print("2. Get API key from: https://console.developers.google.com/")
    print("3. Enable YouTube Data API v3 for your project")
    print("4. Example: export YOUTUBE_API_KEY='your_api_key_here'")
    print("5. Without API key, basic metadata will be returned")
