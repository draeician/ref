#!/usr/bin/env python3
"""
Transcript JSON File Validator

This script checks all transcript JSON files for validity and structural integrity.
It displays progress with an overwriting status line and lists any problematic files.

Author: AI Assistant
Purpose: Ensure data integrity for transcript JSON files after metadata enhancements
"""

import os
import json
import glob
import sys
import argparse
from pathlib import Path
import yaml

def get_transcripts_directory():
    """
    Get the transcripts directory from the configuration.
    
    Returns:
        str: Path to the transcripts directory
    """
    # Try to load from the config file first
    config_dir = os.path.join(os.path.expanduser("~"), '.config', 'ref')
    config_file = os.path.join(config_dir, 'config.yaml')
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
                return os.path.expanduser(config['paths']['transcripts'])
        except Exception as e:
            print(f"Warning: Could not load config file: {e}")
    
    # Fallback to default path
    return os.path.expanduser("~/references/transcripts")

def clear_status_line():
    """Clear the current status line."""
    print("\r" + " " * 80 + "\r", end="", flush=True)

def print_status(message):
    """Print a status message that can be overwritten."""
    clear_status_line()
    print(f"\r{message}", end="", flush=True)

def validate_json_structure(data, filename):
    """
    Validate the expected structure of a transcript JSON file.
    
    Args:
        data (dict): The parsed JSON data
        filename (str): The filename for error reporting
        
    Returns:
        list: List of validation errors (empty if valid)
    """
    errors = []
    
    # Check for required top-level keys
    required_keys = ['transcript', 'duration', 'comments', 'metadata']
    for key in required_keys:
        if key not in data:
            errors.append(f"Missing required key: '{key}'")
    
    # Check transcript field
    if 'transcript' in data:
        if not isinstance(data['transcript'], str):
            errors.append("'transcript' should be a string")
        elif not data['transcript'].strip():
            errors.append("'transcript' is empty")
    
    # Check duration field
    if 'duration' in data:
        if not isinstance(data['duration'], (int, float)):
            errors.append("'duration' should be a number")
        elif data['duration'] < 0:
            errors.append("'duration' should be non-negative")
    
    # Check comments field
    if 'comments' in data:
        if not isinstance(data['comments'], list):
            errors.append("'comments' should be a list")
    
    # Check metadata structure
    if 'metadata' in data:
        if not isinstance(data['metadata'], dict):
            errors.append("'metadata' should be a dictionary")
        else:
            metadata = data['metadata']
            required_metadata_keys = ['id', 'title', 'channel', 'published_at']
            for key in required_metadata_keys:
                if key not in metadata:
                    errors.append(f"Missing metadata key: '{key}'")
                elif not isinstance(metadata[key], str):
                    errors.append(f"Metadata '{key}' should be a string")
    
    return errors

def check_transcript_files(transcripts_dir=None, pattern="*.json", verbose=False, quiet=False):
    """
    Check all transcript JSON files for validity and structure.
    
    Args:
        transcripts_dir (str, optional): Directory to check. If None, uses config default.
        pattern (str): File pattern to match. Defaults to "*.json".
        verbose (bool): Enable verbose output.
        quiet (bool): Suppress progress messages.
    
    Returns:
        tuple: (total_files, valid_files, invalid_files_list)
    """
    if transcripts_dir is None:
        transcripts_dir = get_transcripts_directory()
    
    if not os.path.exists(transcripts_dir):
        print(f"Error: Transcripts directory does not exist: {transcripts_dir}")
        return 0, 0, []
    
    # Find all JSON files in the transcripts directory
    json_pattern = os.path.join(transcripts_dir, pattern)
    json_files = glob.glob(json_pattern)
    
    if not json_files:
        if not quiet:
            print(f"No files matching '{pattern}' found in: {transcripts_dir}")
        return 0, 0, []
    
    if not quiet:
        print(f"Found {len(json_files)} files matching '{pattern}' in: {transcripts_dir}")
        if not verbose:
            print(f"Checking transcript files...\n")
    
    valid_files = 0
    invalid_files = []
    
    for i, json_file in enumerate(json_files, 1):
        filename = os.path.basename(json_file)
        
        if verbose:
            print(f"Checking [{i}/{len(json_files)}]: {filename}")
        elif not quiet:
            print_status(f"Checking [{i}/{len(json_files)}]: {filename}")
        
        try:
            # Try to load and parse the JSON file
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Validate the structure
            validation_errors = validate_json_structure(data, filename)
            
            if validation_errors:
                invalid_files.append({
                    'file': filename,
                    'path': json_file,
                    'errors': validation_errors,
                    'type': 'structure'
                })
                if verbose:
                    print(f"  ⚠️  Structure issues: {len(validation_errors)} errors")
            else:
                valid_files += 1
                if verbose:
                    print(f"  ✅ Valid")
                
        except json.JSONDecodeError as e:
            invalid_files.append({
                'file': filename,
                'path': json_file,
                'errors': [f"JSON decode error: {str(e)}"],
                'type': 'json'
            })
            if verbose:
                print(f"  ❌ JSON error: {str(e)}")
        except Exception as e:
            invalid_files.append({
                'file': filename,
                'path': json_file,
                'errors': [f"File read error: {str(e)}"],
                'type': 'file'
            })
            if verbose:
                print(f"  🔧 File error: {str(e)}")
    
    if not quiet and not verbose:
        clear_status_line()
    return len(json_files), valid_files, invalid_files

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Validate transcript JSON files for structure and syntax.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Check all JSON files (default)
  %(prog)s --verbose                # Show detailed progress for each file
  %(prog)s --quiet                  # Only show summary results
  %(prog)s --directory /path/to/dir # Check specific directory
  %(prog)s --pattern "*.json"       # Check files matching pattern
  %(prog)s --output json            # Output results in JSON format
        """
    )
    
    parser.add_argument(
        "-d", "--directory",
        help="Directory containing transcript files (default: from config)"
    )
    
    parser.add_argument(
        "-p", "--pattern",
        default="*.json",
        help="File pattern to match (default: *.json)"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed progress for each file"
    )
    
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Only show summary results"
    )
    
    parser.add_argument(
        "-o", "--output",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)"
    )
    
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only list problematic files, don't show detailed errors"
    )
    
    return parser.parse_args()

def output_results_json(total_files, valid_files, invalid_files):
    """Output results in JSON format."""
    result = {
        "summary": {
            "total_files": total_files,
            "valid_files": valid_files,
            "invalid_files": len(invalid_files)
        },
        "problematic_files": invalid_files
    }
    
    print(json.dumps(result, indent=2))

def main():
    """Main function to run the transcript file checker."""
    args = parse_arguments()
    
    # Handle conflicting options
    if args.verbose and args.quiet:
        print("Error: --verbose and --quiet cannot be used together")
        sys.exit(1)
    
    if not args.quiet:
        print("=" * 60)
        print("TRANSCRIPT JSON FILE VALIDATOR")
        print("=" * 60)
    
    total_files, valid_files, invalid_files = check_transcript_files(
        transcripts_dir=args.directory,
        pattern=args.pattern,
        verbose=args.verbose,
        quiet=args.quiet
    )
    
    if total_files == 0:
        return
    
    # Handle different output formats
    if args.output == "json":
        output_results_json(total_files, valid_files, invalid_files)
        sys.exit(1 if invalid_files else 0)
    
    # Text output format (default)
    if not args.quiet:
        print(f"\nValidation Summary:")
        print(f"==================")
        print(f"Total files checked: {total_files}")
        print(f"Valid files: {valid_files}")
        print(f"Invalid files: {len(invalid_files)}")
    
    if invalid_files:
        if not args.quiet:
            if args.list_only:
                print(f"\nProblematic Files:")
                print(f"==================")
                for file_info in invalid_files:
                    print(f"   • {file_info['file']} ({file_info['type']})")
            else:
                print(f"\nProblematic Files:")
                print(f"==================")
                
                # Group by error type
                json_errors = [f for f in invalid_files if f['type'] == 'json']
                structure_errors = [f for f in invalid_files if f['type'] == 'structure']
                file_errors = [f for f in invalid_files if f['type'] == 'file']
                
                if json_errors:
                    print(f"\n❌ JSON Parse Errors ({len(json_errors)} files):")
                    for file_info in json_errors:
                        print(f"   • {file_info['file']}")
                        if not args.list_only:
                            for error in file_info['errors']:
                                print(f"     - {error}")
                
                if structure_errors:
                    print(f"\n⚠️  Structure Issues ({len(structure_errors)} files):")
                    for file_info in structure_errors:
                        print(f"   • {file_info['file']}")
                        if not args.list_only:
                            for error in file_info['errors']:
                                print(f"     - {error}")
                
                if file_errors:
                    print(f"\n🔧 File Access Errors ({len(file_errors)} files):")
                    for file_info in file_errors:
                        print(f"   • {file_info['file']}")
                        if not args.list_only:
                            for error in file_info['errors']:
                                print(f"     - {error}")
            
            if not args.list_only:
                print(f"\nRecommendation: Review and fix the problematic files listed above.")
        
        sys.exit(1)
    else:
        if not args.quiet:
            print(f"\n✅ All transcript JSON files are valid!")
            print(f"   All {total_files} files passed validation checks.")
        sys.exit(0)

if __name__ == "__main__":
    main()
