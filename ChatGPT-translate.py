import os
import re
from tqdm import tqdm
import argparse
import time
from os import environ as env
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
import openai
import trafilatura

ALLOWED_FILE_TYPES = [".txt", ".md", ".rtf", ".html"]


class ChatGPT:

    def __init__(self, key, target_language, not_to_translate_people_names):
        self.key = key
        self.target_language = target_language
        self.last_request_time = 0
        self.request_interval = 1  # seconds
        self.max_backoff_time = 60  # seconds
        self.not_to_translate_people_names = not_to_translate_people_names

    def translate(self, text):
        # Set up OpenAI API key
        openai.api_key = self.key
        # lang
        while True:
            try:
                # Check if enough time has passed since the last request
                elapsed_time = time.monotonic() - self.last_request_time
                if elapsed_time < self.request_interval:
                    time.sleep(self.request_interval - elapsed_time)
                self.last_request_time = time.monotonic()
                # change prompt based on not_to_translate_people_names
                if self.not_to_translate_people_names:
                    completion = openai.ChatCompletion.create(
                        model="gpt-3.5-turbo",
                        messages=[{
                            'role': 'system',
                            'content': 'You are a translator assistant.'
                        }, {
                            "role":
                            "user",
                            "content":
                            f"Translate the following text into {self.target_language} in a way that is faithful to the original text. Do not translate people and authors' names. Return only the translation and nothing else:\n{text}",
                        }],
                    )
                else:
                    completion = openai.ChatCompletion.create(
                        model="gpt-3.5-turbo",
                        messages=[{
                            'role': 'system',
                            'content': 'You are a translator assistant.'
                        }, {
                            "role":
                            "user",
                            "content":
                            f"Translate the following text into {self.target_language} in a way that is faithful to the original text. Return only the translation and nothing else:\n{text}",
                        }],
                    )
                t_text = (completion["choices"][0].get("message").get(
                    "content").encode("utf8").decode())
                break
            except Exception as e:
                print(str(e))
                # Exponential backoff if rate limit is hit
                self.request_interval *= 2
                if self.request_interval > self.max_backoff_time:
                    self.request_interval = self.max_backoff_time
                print(
                    f"Rate limit hit. Sleeping for {self.request_interval} seconds."
                )
                time.sleep(self.request_interval)
                continue

        return t_text


def translate_text_file(text_filepath_or_url, options):
    OPENAI_API_KEY = options.openai_key or os.environ.get("OPENAI_API_KEY")
    translator = ChatGPT(OPENAI_API_KEY, options.target_language,
                         options.not_to_translate_people_names)

    paragraphs = read_and_preprocess_data(text_filepath_or_url)

    # keep first three paragraphs
    first_three_paragraphs = paragraphs[:3]

    # if users require to ignore References, we then take out all paragraphs after the one starting with "References"
    if options.include_references:
        for i, p in enumerate(paragraphs):
            if p.startswith("References"):
                print("References will not be translated.")
                ref_paragraphs = paragraphs[i:]
                paragraphs = paragraphs[:i]
                break

        with ThreadPoolExecutor(max_workers=options.num_threads) as executor:
            translated_paragraphs = list(
                tqdm(executor.map(translator.translate, paragraphs),
                     total=len(paragraphs),
                     desc="Translating paragraphs",
                     unit="paragraph"))
            translated_paragraphs = [p.strip() for p in translated_paragraphs]

        translated_text = "\n".join(translated_paragraphs)
    if options.bilingual:
        bilingual_text = "\n".join(f"{paragraph}\n{translation}"
                                   for paragraph, translation in zip(
                                       paragraphs, translated_paragraphs))
        # add first three paragraphs if required
        if options.keep_first_three_paragraphs:
            bilingual_text = "\n".join(
                first_three_paragraphs) + "\n" + bilingual_text
        # append References
        if options.include_references:
            bilingual_text += "\n".join(ref_paragraphs)
        output_file = f"{Path(text_filepath_or_url).parent}/{Path(text_filepath_or_url).stem}_bilingual.txt"
        with open(output_file, "w") as f:
            f.write(bilingual_text)
            print(f"Bilingual text saved to {f.name}.")
    else:
        # remove extra newlines
        translated_text = re.sub(r"\n{2,}", "\n", translated_text)
        # add first three paragraphs if required
        if options.keep_first_three_paragraphs:
            translated_text = "\n".join(
                first_three_paragraphs) + "\n" + translated_text
        # append References
        if options.include_references:
            translated_text += "\n".join(ref_paragraphs)
        output_file = f"{Path(text_filepath_or_url).parent}/{Path(text_filepath_or_url).stem}_translated.txt"
        with open(output_file, "w") as f:
            f.write(translated_text)
            print(f"Translated text saved to {f.name}.")


import requests


def download_html(url):
    response = requests.get(url)
    return response.text


def read_and_preprocess_data(text_filepath_or_url):
    if text_filepath_or_url.startswith('http'):
        # replace "https:/www" with "https://www"
        text_filepath_or_url = text_filepath_or_url.replace(":/", "://")
        # download and extract text from URL
        print("Downloading and extracting text from URL...")
        downloaded = trafilatura.fetch_url(text_filepath_or_url)
        print("Downloaded text:")
        print(downloaded)
        text = trafilatura.extract(downloaded)
    else:
        with open(text_filepath_or_url, "r", encoding='utf-8') as f:
            text = f.read()
            if text_filepath_or_url.endswith('.html'):
                # extract text from HTML file
                print("Extracting text from HTML file...")
                text = trafilatura.extract(text)
                # write to a txt file ended with "_extracted"
                with open(
                        f"{Path(text_filepath_or_url).parent}/{Path(text_filepath_or_url).stem}_extracted.txt",
                        "w") as f:
                    f.write(text)
                    print(f"Extracted text saved to {f.name}.")
    paragraphs = [p.strip() for p in text.split("\n") if p.strip() != ""]
    return paragraphs


def parse_arguments():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input_path",
        dest="input_path",
        type=str,
        help="input file or folder to translate",
    )
    parser.add_argument(
        "--openai_key",
        dest="openai_key",
        type=str,
        default="",
        help="OpenAI API key",
    )
    parser.add_argument(
        "--num_threads",
        dest="num_threads",
        type=int,
        default=10,
        help="number of threads to use for translation",
    )
    parser.add_argument(
        "--bilingual",
        dest="bilingual",
        action="store_true",
        default=False,
        help=
        "output bilingual txt file with original and translated text side by side",
    )
    parser.add_argument(
        "--target_language",
        dest="target_language",
        type=str,
        default="Simplified Chinese",
        help="target language to translate to",
    )

    parser.add_argument(
        "--not_to_translate_people_names",
        dest="not_to_translate_people_names",
        action="store_true",
        default=True,
        help="whether or not to translate names in the text",
    )
    parser.add_argument(
        "--include_references",
        dest="include_references",
        action="store_true",
        default=True,
        help="not to translate references",
    )
    parser.add_argument(
        "--keep_first_three_paragraphs",
        dest="keep_first_three_paragraphs",
        action="store_true",
        default=True,
        help="keep the first three paragraphs of the original text",
    )

    options = parser.parse_args()
    OPENAI_API_KEY = options.openai_key or os.environ.get("OPENAI_API_KEY")
    if not OPENAI_API_KEY:
        raise Exception("Please provide your OpenAI API key")
    return options

def check_file_path(file_path: Path, options=None):
    """
    Ensure file extension is in ALLOWED_FILE_TYPES or is a URL.
    If file ends with _translated.txt or _bilingual.txt, skip it.
    If there is any txt file ending with _translated.txt or _bilingual.txt, skip it.
    """
    if not file_path.suffix.lower() in ALLOWED_FILE_TYPES and not str(file_path).startswith('http'):
        raise Exception("Please use a txt file or URL")

    if file_path.stem.endswith("_translated") or file_path.stem.endswith("extracted_translated"):
        print(f"You already have a translated file for {file_path}, skipping...")
        return False
    elif file_path.stem.endswith("_bilingual") or file_path.stem.endswith("extracted_bilingual"):
        print(f"You already have a bilingual file for {file_path}, skipping...")
        return False

    if (file_path.with_name(f"{file_path.stem}_translated{file_path.suffix}").exists() or
            file_path.with_name(f"{file_path.stem}_extracted_translated{file_path.suffix}").exists()) and not (options and options.get('bilingual', False)):
        print(f"You already have a translated file for {file_path}, skipping...")
        return False
    elif (file_path.with_name(f"{file_path.stem}_bilingual{file_path.suffix}").exists() or
            file_path.with_name(f"{file_path.stem}_extracted_bilingual{file_path.suffix}").exists()) and (options and options.get('bilingual', False)):
        print(f"You already have a bilingual file for {file_path}, skipping...")
        return False

    return True

def process_file(file_path, options):
    """Translate a single text file"""
    if not check_file_path(file_path, options):
        return
    print(f"Translating {file_path}...")
    translate_text_file(str(file_path), options)


def process_folder(folder_path, options):
    """Translate all text files in a folder"""
    files_to_process = list(folder_path.rglob("*"))
    total_files = len(files_to_process)
    for index, file_path in enumerate(files_to_process):
        if file_path.is_file() and file_path.suffix.lower(
        ) in ALLOWED_FILE_TYPES:
            process_file(file_path, options)
        print(
            f"Processed file {index + 1} of {total_files}. Only {total_files - index - 1} files left to process."
        )


def main():
    """Main function"""
    options = parse_arguments()
    input_path = Path(options.input_path)
    if input_path.is_dir():
        # input path is a folder, scan and process all allowed file types
        process_folder(input_path, options)
    elif input_path.is_file:
        process_file(input_path, options)


if __name__ == "__main__":
    main()
