import argparse
import logging
from dataclasses import dataclass
from functools import cache, wraps
from pprint import pprint
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


@dataclass
class Creator:
    id: str
    name: str
    service: str

    @classmethod
    def from_json(cls, json: dict[str, str]) -> 'Creator':
        return cls(id=json['id'], name=json['name'], service=json['service'])


@dataclass
class KemonoAttachment:
    name: str
    path: str
    server: str

    @classmethod
    def from_json(cls, json: dict[str, str]) -> 'KemonoAttachment':
        return cls(
            name=json['name'],
            path=json['path'],
            server=json['server'],
        )


@dataclass
class KemonoPost:
    id: str
    title: str
    pictures: Iterable[KemonoAttachment]
    file_attachments: Iterable[KemonoAttachment]

    @classmethod
    def from_json(cls, json: dict[str, str]) -> 'KemonoPost':
        pictures = [
            KemonoAttachment.from_json(picture_json)
            for picture_json in json['previews']
        ]
        file_attachments = [
            KemonoAttachment.from_json(attachment_json)
            for attachment_json in json['attachments']
        ]

        return cls(
            id=json['post']['id'],
            title=json['post']['title'],
            pictures=pictures,
            file_attachments=file_attachments,
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
@tenacity.retry(
    stop=tenacity.stop_after_attempt(5),
)
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
@tenacity.retry(
    stop=tenacity.stop_after_attempt(5),
)
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


def main_cli() -> None:
    args = construct_argparser().parse_args()
    for url in args.URLS:
        service, creator_id, post_id = url.split('/')[3::2]
        post_data = get_post_data(service, creator_id, post_id)
        creator_data = get_creator_data(creator_id, service)
        pprint(creator_data)
        pprint(post_data)
        print('--------')


if __name__ == '__main__':
    main_cli()
