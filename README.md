# Khinsider downloader

Script to download posts from https://kemono.su

Requires python 3.12+ (May work on versions down to 3.10)

## Installation
```bash
$ pip install git+https://github.com/NovaHFly/kemono_su_downloader
```

## Usage
- Linux
```bash
$ python3 -m kemono [-h] [--threads THREADS] URLS ...
```
- Windows with py launcher
```cmd
> py -m kemono [-h] [--threads THREADS] URLS ...
```

## Used libraries
- [httpx](https://www.python-httpx.org/)
- [tenacity](https://github.com/jd/tenacity)
