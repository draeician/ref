from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build
from typing import Dict, Optional, Any
import json
import os

# You'll need to set your YouTube Data API key as an environment variable
# Get your API key from: https://console.developers.google.com/
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

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
            - duration: Total duration in seconds (as integer)
            - comments: Empty array (placeholder)
            - metadata: Video metadata (id, title, channel, published_at)
            
    Raises:
        Exception: If transcript or metadata cannot be fetched or file cannot be written
    """
    try:
        # Fetch the transcript
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        
        # Extract text segments and calculate duration
        text_segments = []
        total_duration = 0.0
        
        for segment in transcript_list:
            text_segments.append(segment['text'])
            total_duration += segment['duration']
        
        # Combine all text segments into one string
        complete_text = ' '.join(text_segments)
        
        # Fetch video metadata using YouTube Data API
        metadata = get_video_metadata(video_id, api_key or YOUTUBE_API_KEY)
        
        # Construct the JSON response
        result = {
            "transcript": complete_text,
            "duration": int(total_duration),  # Convert to int as shown in your example
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
        
    except Exception as e:
        raise Exception(f"Failed to fetch transcript and metadata for video {video_id}: {str(e)}")

def get_video_metadata(video_id: str, api_key: str) -> Dict[str, str]:
    """
    Fetches video metadata using YouTube Data API v3.
    
    Args:
        video_id (str): YouTube video ID
        api_key (str): YouTube Data API key
        
    Returns:
        Dict[str, str]: Video metadata dictionary
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
        
        if not response['items']:
            raise Exception(f"Video {video_id} not found")
        
        video_info = response['items'][0]['snippet']
        
        return {
            "id": video_id,
            "title": video_info['title'],
            "channel": video_info['channelTitle'],
            "published_at": video_info['publishedAt']
        }
        
    except Exception as e:
        # Fallback metadata if API call fails
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
        # Fetch the transcript
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        
        # Extract text segments and durations
        text_segments = []
        total_duration = 0.0
        
        for segment in transcript_list:
            text_segments.append(segment['text'])
            total_duration += segment['duration']
        
        # Combine all text segments into one string
        complete_text = ' '.join(text_segments)
        
        return complete_text, total_duration
        
    except Exception as e:
        raise Exception(f"Failed to fetch transcript for video {video_id}: {str(e)}")

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
        if languages:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        else:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        
        text_segments = []
        total_duration = 0.0
        
        for segment in transcript_list:
            text_segments.append(segment['text'])
            total_duration += segment['duration']
        
        complete_text = ' '.join(text_segments)
        
        return complete_text, total_duration
        
    except Exception as e:
        raise Exception(f"Failed to fetch transcript for video {video_id}: {str(e)}")

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

"""
YouTube Transcript API with Metadata

This module provides functions to fetch YouTube video transcripts and metadata,
returning structured JSON data that includes the complete transcript text,
video duration, and video metadata (title, channel, published date).

ASSUMPTION: English language transcripts only. The API will fetch the primary 
transcript which is typically English for English-language videos.

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