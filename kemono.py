import argparse
import logging
from dataclasses import dataclass, field
from functools import cache, wraps
from itertools import chain
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

    @classmethod
    def from_json(
        cls, json: dict[str, str], filename: str = None
    ) -> 'KemonoAttachment':
        if not filename:
            filename = json['name']
        return cls(
            name=json['name'],
            path=json['path'],
            server=json['server'],
            filename=filename,
        )


@dataclass
class KemonoPost:
    id: str = field(repr=False)
    title: str
    pictures: Iterable[KemonoAttachment] = field(repr=False)
    file_attachments: Iterable[KemonoAttachment] = field(repr=False)
    creator: Creator

    @classmethod
    def from_json(cls, json: dict[str, str]) -> 'KemonoPost':
        pictures = [
            KemonoAttachment.from_json(
                picture_json,
                filename=(
                    f'{picture_number}'
                    f'.{picture_json["path"].rsplit(".", maxsplit=1)[-1]}'
                ),
            )
            for picture_number, picture_json in enumerate(
                json['previews'], start=1
            )
        ]
        file_attachments = [
            KemonoAttachment.from_json(attachment_json)
            for attachment_json in json['attachments']
        ]
        creator = get_creator_data(
            creator_id=json['post']['user'],
            service=json['post']['service'],
        )

        return cls(
            id=json['post']['id'],
            title=json['post']['title'],
            pictures=pictures,
            file_attachments=file_attachments,
            creator=creator,
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
    downloads_folder: Path = DEFAULT_DOWNLOADS_PATH,
) -> None:
    file_path = downloads_folder / attachment.filename

    logging.info(f'{attachment} submitted for download')

    res = httpx.get(
        attachment.server + '/data' + attachment.path
    ).raise_for_status()

    with file_path.open('wb') as f:
        f.write(res.content)

    logging.info(f'{attachment}: download completed')


def download_post(
    post: KemonoPost,
) -> None:
    folder_name = f'[{post.creator.name}] {post.title} ({post.id})'
    folder_path = DEFAULT_DOWNLOADS_PATH / folder_name
    folder_path.mkdir(exist_ok=True, parents=True)

    logging.info(f'{post} submitted for download')

    for attachment in chain(post.pictures, post.file_attachments):
        download_file(
            attachment,
            downloads_folder=folder_path,
        )

    logging.info(f'{post}: download completed')


def main_cli() -> None:
    args = construct_argparser().parse_args()
    for url in args.URLS:
        service, creator_id, post_id = url.split('/')[3::2]
        download_post(get_post_data(service, creator_id, post_id))
        print('--------')


if __name__ == '__main__':
    main_cli()
