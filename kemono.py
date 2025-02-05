import argparse
import logging
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from functools import cache, wraps
from pathlib import Path
from typing import Callable, Iterable, ParamSpec, TypeVar

import httpx
import tenacity

logging.basicConfig(
    level=logging.INFO,
    filename='main.log',
    filemode='a',
    format='%(asctime)s, %(levelname)s, %(message)s, %(name)s',
)
logging.getLogger().addHandler(logging.StreamHandler())

P = ParamSpec('P')
T = TypeVar('T')

Decorator = Callable[[Callable[P, T]], Callable[P, T]]
ExceptionGroup = tuple[Exception, ...]

DEFAULT_DOWNLOADS_PATH = Path('downloads')


@dataclass
class Creator:
    id: str = field(repr=False)
    name: str
    service: str = field(repr=False)

    @classmethod
    def from_json(cls, json: dict[str, str]) -> 'Creator':
        return cls(id=json['id'], name=json['name'], service=json['service'])


@dataclass
class KemonoAttachment:
    name: str = field(repr=False)
    path: str = field(repr=False)
    server: str = field(repr=False)
    filename: str
    parent_path: Path = field(repr=False)

    @classmethod
    def from_json(
        cls,
        json: dict[str, str],
        filename: str = None,
        folder_path: Path = None,
    ) -> 'KemonoAttachment':
        if not filename:
            filename = json['name']
        if not folder_path:
            folder_path = DEFAULT_DOWNLOADS_PATH
        return cls(
            name=json['name'],
            path=json['path'],
            server=json['server'],
            filename=filename,
            parent_path=folder_path,
        )


@dataclass
class KemonoPost:
    id: str = field(repr=False)
    title: str
    pictures: Iterable[KemonoAttachment] = field(repr=False)
    file_attachments: Iterable[KemonoAttachment] = field(repr=False)
    folder_path: Path = field(repr=False)
    creator: Creator

    @classmethod
    def from_json(cls, json: dict[str, str]) -> 'KemonoPost':
        creator = get_creator_data(
            creator_id=json['post']['user'],
            service=json['post']['service'],
        )
        post_id = json['post']['id']
        title = json['post']['title']

        folder_path = (
            DEFAULT_DOWNLOADS_PATH / f'[{creator.name}] {title} ({post_id})'
        )

        pictures = [
            KemonoAttachment.from_json(
                picture_json,
                filename=(
                    f'{picture_number}'
                    f'.{picture_json["path"].rsplit(".", maxsplit=1)[-1]}'
                ),
                folder_path=folder_path,
            )
            for picture_number, picture_json in enumerate(
                json['previews'], start=1
            )
        ]
        file_attachments = [
            KemonoAttachment.from_json(
                attachment_json, folder_path=folder_path
            )
            for attachment_json in json['attachments']
        ]

        return cls(
            id=json['post']['id'],
            title=json['post']['title'],
            pictures=pictures,
            file_attachments=file_attachments,
            creator=creator,
            folder_path=folder_path,
        )


def construct_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument('URLS', help='kemono.su urls', nargs='+')
    return parser


def log_errors(
    func: Callable[P, T] = None,
    *,
    expected_exceptions: ExceptionGroup = (Exception,),
) -> Callable[P, T] | Decorator:
    """A decorator to log exceptions.

    If the decorated function raises one of expected exceptions,
    it will be logged and re-raised.

    Decorator can be used with or without arguments.
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except expected_exceptions as e:
                logging.error(e)
                raise

        return wrapper

    if func:
        return decorator(func)

    return decorator


def log_time(func: Callable[P, T]) -> Callable[P, T]:
    """Decorator to log real time elapsed by function."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        logging.info(
            f'{func.__name__} took {end_time - start_time:.2f} seconds'
        )
        return result

    return wrapper


@log_errors
@cache
@tenacity.retry(stop=tenacity.stop_after_attempt(5))
def get_creator_data(
    creator_id: str,
    service: str,
) -> Creator:
    return Creator.from_json(
        httpx.get(
            f'https://kemono.su/api/v1/{service}/user/{creator_id}/profile',
        )
        .raise_for_status()
        .json()
    )


@log_errors
@tenacity.retry(stop=tenacity.stop_after_attempt(5))
def get_post_data(
    service: str,
    creator_id: str,
    post_id: str,
) -> KemonoPost:
    return KemonoPost.from_json(
        httpx.get(
            f'https://kemono.su/api/v1/{service}/user/{creator_id}/post/{post_id}',
        )
        .raise_for_status()
        .json()
    )


@log_errors
@tenacity.retry(stop=tenacity.stop_after_attempt(5))
def download_file(
    attachment: KemonoAttachment,
) -> Path:
    file_path = attachment.parent_path / attachment.filename
    file_path.parent.mkdir(exist_ok=True, parents=True)

    logging.info(f'{attachment} submitted for download')

    res = httpx.get(
        attachment.server + '/data' + attachment.path
    ).raise_for_status()

    with file_path.open('wb') as f:
        f.write(res.content)

    logging.info(f'{attachment}: download completed')

    return file_path


@log_time
def main_cli() -> None:
    args = construct_argparser().parse_args()
    with ThreadPoolExecutor(max_workers=5) as executor:
        post_fetch_tasks = [
            executor.submit(get_post_data, *url.split('/')[3::2])
            for url in args.URLS
        ]

        post_attachments = sum(
            (
                [*post.pictures, *post.file_attachments]
                for post in (task.result() for task in post_fetch_tasks)
            ),
            start=[],
        )

        attachment_download_tasks = [
            executor.submit(download_file, attachment)
            for attachment in post_attachments
        ]

        wait(attachment_download_tasks)

    total_files_submitted = len(attachment_download_tasks)

    successful_downloads = [
        task for task in attachment_download_tasks if not task.exception()
    ]
    total_files_downloaded = len(successful_downloads)

    total_file_size = sum(
        task.result().stat().st_size for task in successful_downloads
    )
    logging.info(
        f'Downloaded {total_files_downloaded} out of {total_files_submitted}'
    )
    logging.info(
        f'Total download size: {total_file_size / 1024 / 1024:.2f} MB'
    )


if __name__ == '__main__':
    main_cli()
