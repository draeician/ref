#!/usr/bin/env python3
import os
import sys
import subprocess

def process_url(url: str) -> str:
    # Determine if the URL contains special characters
    if any(char in url for char in ['?', '&', '=', '+']):
        # Run with quotes
        command = f'./ref6 "{url}"'
    else:
        # Run without quotes
        command = f'./ref6 {url}'

    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        return f"SUCCESS: {url}\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"ERROR: {url}\n{e.stderr}"

def main():
    if len(sys.argv) != 2:
        print("Usage: readd <filename>")
        sys.exit(1)

    filename = sys.argv[1]
    
    if not os.path.isfile(filename):
        print(f"File {filename} does not exist.")
        sys.exit(1)

    success_log = "success.log"
    error_log = "error.log"

    with open(filename, 'r') as file:
        urls = file.readlines()

    with open(success_log, 'w') as success_file, open(error_log, 'w') as error_file:
        for url in urls:
            url = url.strip()
            if url:
                result = process_url(url)
                if result.startswith("SUCCESS"):
                    success_file.write(result)
                    print(result)
                else:
                    error_file.write(result)
                    print(result, file=sys.stderr)

if __name__ == "__main__":
    main()
