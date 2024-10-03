
# URL Reference Tool

This is a command-line tool written in Python for adding URLs to markdown files. It allows you to easily record URLs along with their metadata, such as title and date, in separate Markdown files. The updated version of this tool includes improved error handling, cleaner and more concise code, better user interaction, support for resolving URL redirects, and the ability to fetch YouTube video transcripts.

## Features

- Add URLs to markdown files for easy reference.
- Support for YouTube URLs, YouTube channel URLs, and general URLs.
- Fetches title information from the webpage for general URLs.
- Fetches YouTube video transcripts and stores them in a specified directory.
- Handles duplicate URL prevention based on existing records.
- Resolves URL redirects, including handling YouTube redirect URLs.
- Improved error handling and user experience.

## Requirements

- Python 3.x
- `argparse` library
- `requests` library
- `beautifulsoup4` library
- `google-api-python-client` library
- `python-dotenv` library

## Installation

1. Clone the repository:
   ```shell
   git clone <repository-url>
   cd ref-program
   ```

2. Install the required dependencies:
   ```shell
   pip install -r requirements.txt
   ```

3. Set up the environment file:
   Create a `.env` file in your home directory (`~/.env`) and add your YouTube API key:
   ```
   YOUTUBE_API_KEY=your_youtube_api_key_here
   ```

4. Create the configuration file:
   Create a `config.yaml` file in the `.config/ref` directory in your home directory:
   ```yaml
   removable_keys:
     - 'utm_source'
     - 'utm_medium'
     - 'utm_campaign'
     - 'utm_term'
     - 'utm_content'
     - 'rdt_cid'
     - 'linkCode'
     - 'tag'
     - 'topicId'
     - 'ref_'
     - 'ascsubtag'
     - 'share_id'
     - 'fbclid'
     - 'gclid'
     - 'igshid'
     - 'rdt'
     - 'utm_name'
   paths:
     references: "~/references"
     transcripts: "~/transcripts"
   ```

## Usage

To use the URL reference tool, run the following command:

```shell
python ref.py <url> [-f] [-e] [--version]
```

- `<url>`: The URL to be added.
- `-f, --force`: Force addition even if the URL already exists.
- `-e, --edit`: Open the markdown file for editing.
- `--version`: Display the version of the URL reference tool.

## Examples

- Add a YouTube video URL and fetch its transcript:
  ```shell
  python ref.py https://www.youtube.com/watch?v=abcdefgh
  ```

- Add a general URL:
  ```shell
  python ref.py https://www.example.com
  ```

- Force addition of a URL even if it already exists:
  ```shell
  python ref.py -f https://www.example.com
  ```

- Open the YouTube references file for editing:
  ```shell
  python ref.py -e https://www.youtube.com/@username
  ```

- Display the version of the URL reference tool:
  ```shell
  python ref.py --version
  ```

- Handle YouTube redirect URL:
  ```shell
  python ref.py "https://www.youtube.com/redirect?event=video_description&redir_token=QUFFLUhqbF8xaGtKQl9jQVN1NlZINGxHcExuckg0eGd1QXxBQ3Jtc0tuQkhkWmFqaHlRLVBXWXFyMGF4MkhUNmQ2UTNLZHlrRTVfa210ZjNPRVhnZDZJTFdJRXdnSUdhb2xCNE5JUHN1M0FuSm1wMDNTWDk3Y2RENmx0akNKZkZzMzVVbXJnYXRJaWUwOUoxcWZkd2twdzNnVQ&q=https%3A%2F%2Fgithub.com%2Faaedmusa%2FCapstan-Drive&v=MwIBTbumd1Q"
  ```

## File Structure

- `ref.py`: The main Python script for the URL reference tool.
- `references/`: Directory containing the markdown files.
  - `references/youtube_references.md`: Markdown file for recording YouTube-related URLs.
  - `references/links.md`: Markdown file for recording general URLs.
- `transcripts/`: Directory containing the YouTube video transcripts.

## Browser Extension

We have also created a browser extension to copy URLs of all open tabs to the clipboard. This extension is compatible with both Chrome and Firefox. For more details on how to install and use the browser extension, please refer to the [browser extension documentation](extension/README.md).

## Contributing

Contributions to this URL reference tool are welcome! Feel free to open issues or submit pull requests for any enhancements, bug fixes, or additional features.

## License

This project is licensed under the MIT License.

