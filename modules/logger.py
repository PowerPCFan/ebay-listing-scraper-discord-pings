import logging
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .global_vars import config
from . import webhook_sender

_discord_webhook_send_count = 0
setLevelValue = logging.DEBUG if config.debug_mode else logging.INFO
LOGGER_DISCORD_WEBHOOK_URL = config.logger_webhook

ANSI = "\033["
RESET = f"{ANSI}0m"
RED = f"{ANSI}31m"
GREEN = f"{ANSI}32m"
BLUE = f"{ANSI}34m"
YELLOW = f"{ANSI}33m"
WHITE = f"{ANSI}37m"
PURPLE = f"{ANSI}35m"
CYAN = f"{ANSI}36m"
LIGHT_CYAN = f"{ANSI}96m"
SUPER_LIGHT_CYAN = f"{ANSI}38;5;153m"
ORANGE = f"{ANSI}38;5;208m"


class Logger(logging.Formatter):
    def __init__(self) -> None:
        super().__init__()
        self._format = "[ %(levelname)s ]    %(message)s    [%(asctime)s (%(filename)s:%(funcName)s)]"
        self.utc_minus_5 = timezone(timedelta(hours=-5))

        self.FORMATS = {
            logging.DEBUG: self._format,
            logging.INFO: self._format,
            logging.WARNING: self._format,
            logging.ERROR: self._format,
            logging.CRITICAL: self._format,
        }

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return datetime.fromtimestamp(record.created, tz=self.utc_minus_5).strftime("%m/%d/%Y %H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        record.levelname = record.levelname.center(8)

        match record.levelno:
            case logging.INFO:
                record.levelname = f"{GREEN}{record.levelname}{RESET}"
            case logging.WARNING:
                record.levelname = f"{YELLOW}{record.levelname}{RESET}"
            case logging.ERROR:
                record.levelname = f"{RED}{record.levelname}{RESET}"
            case logging.CRITICAL:
                record.levelname = f"{PURPLE}{record.levelname}{RESET}"

        log_fmt = self.FORMATS.get(record.levelno)

        formatter = logging.Formatter(log_fmt)
        formatter.formatTime = self.formatTime
        return formatter.format(record)


fmt = Logger()


class FileLogger(logging.Formatter):
    def __init__(self) -> None:
        super().__init__()
        self._format = "[ %(levelname)s ]    %(message)s    [%(asctime)s (%(filename)s:%(funcName)s)]"
        self.utc_minus_5 = timezone(timedelta(hours=-5))

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return datetime.fromtimestamp(record.created, tz=self.utc_minus_5).strftime("%m/%d/%Y %H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        rc = logging.makeLogRecord(record.__dict__)
        rc.levelname = rc.levelname.center(8)

        formatter = logging.Formatter(self._format)
        formatter.formatTime = self.formatTime
        return formatter.format(rc)


class CustomLogger:
    def __init__(self, base_logger: logging.Logger) -> None:
        self.base_logger: logging.Logger = base_logger

    def debug(self, msg: str, *args, **kwargs) -> None:
        # commented out bcz log level handles this + it prevents logging debug to file when debug_mode is off
        # if config.debug_mode:
        return self.base_logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        return self.base_logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        return self.base_logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        return self.base_logger.error(msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs) -> None:
        return self.base_logger.critical(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs) -> None:
        return self.base_logger.exception(msg, *args, **kwargs)

    def log(self, level: int, msg: str, *args, **kwargs) -> None:
        return self.base_logger.log(level, msg, *args, **kwargs)

    @property
    def handlers(self) -> list[logging.Handler]:
        return self.base_logger.handlers

    def addHandler(self, handler: logging.Handler) -> None:
        return self.base_logger.addHandler(handler)

    def removeHandler(self, handler: logging.Handler) -> None:
        return self.base_logger.removeHandler(handler)

    def setLevel(self, level: int) -> None:
        return self.base_logger.setLevel(level)

    def getEffectiveLevel(self) -> int:
        return self.base_logger.getEffectiveLevel()

    async def newline(self) -> None:
        print("\n", end="")

        for handler in self.base_logger.handlers:
            if isinstance(handler, DiscordWebhookHandler):
                try:
                    assert handler.message_queue is not None
                    await handler.message_queue.put("_ _")
                    return
                except Exception:
                    print("[ ERROR ] Failed to queue newline for Discord webhook!")

        try:
            webhook_sender.send(config.logger_webhook, "_ _")
        except Exception:
            print("[ ERROR ] Failed to send newline to Discord webhook!")


class FileLoggingHandler(logging.Handler):
    def __init__(self, log_file_path: str, level: int = logging.NOTSET) -> None:
        super().__init__(level)
        self.log_file_path = Path(log_file_path)
        self.message_queue = None
        self.worker_task = None
        self.shutdown_event = None
        try:
            self._start_worker()
        except Exception as e:
            print(f"[ ERROR ] Failed to setup file logging: {e}")

    def _start_worker(self) -> None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                if self.message_queue is None:
                    self.message_queue = asyncio.Queue()
                if self.shutdown_event is None:
                    self.shutdown_event = asyncio.Event()

                if self.worker_task is None or self.worker_task.done():
                    self.worker_task = asyncio.create_task(self._worker())
            else:
                self.worker_task = None
        except RuntimeError:
            self.worker_task = None

    async def _worker(self) -> None:
        if self.shutdown_event is None or self.message_queue is None:
            return  # No async components initialized

        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)

        while not self.shutdown_event.is_set():
            try:
                content = await asyncio.wait_for(self.message_queue.get(), timeout=1.0)
                if content is None:
                    break

                with open(self.log_file_path, 'a', encoding='utf-8') as f:
                    f.write(content + '\n')
                    f.flush()

                self.message_queue.task_done()

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[ ERROR ] File logging worker error: {e}")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level_name = logging.getLevelName(record.levelno).center(8)
            asctime = datetime.fromtimestamp(record.created).strftime("%m/%d/%Y %H:%M:%S")
            message = record.getMessage()

            content = f"[ {level_name} ]    {message}    [{asctime} ({record.filename}:{record.funcName})]"

            if self.worker_task is None:
                self._start_worker()

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running() and self.message_queue is not None:
                    self.message_queue.put_nowait(content)
                else:
                    self.log_file_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(self.log_file_path, 'a', encoding='utf-8') as f:
                        f.write(content + '\n')
                        f.flush()
            except RuntimeError:
                self.log_file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.log_file_path, 'a', encoding='utf-8') as f:
                    f.write(content + '\n')
                    f.flush()

        except Exception as e:
            print(f"[ ERROR ] Failed to emit file log: {e}")

    def close(self) -> None:
        if self.shutdown_event is not None:
            self.shutdown_event.set()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running() and self.message_queue is not None:
                self.message_queue.put_nowait(None)
                if self.worker_task and not self.worker_task.done():
                    self.worker_task.cancel()
            elif self.message_queue is not None:
                asyncio.run(self.message_queue.put(None))
        except RuntimeError:
            pass
        super().close()


_base_logger = logging.getLogger("ebay-listing-scraper-discord-pings")
_base_logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler()
handler.setFormatter(fmt)
handler.setLevel(setLevelValue)
_base_logger.addHandler(handler)

if config.file_logging:
    try:
        log_dir = Path(__file__).parent.parent / "logs"
        log_file_path = log_dir / f"debug-log-{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}.log"

        file_handler = FileLoggingHandler(str(log_file_path))
        file_handler.setLevel(logging.DEBUG)  # Always log all levels to file
        _base_logger.addHandler(file_handler)
    except Exception as e:
        print(f"[ ERROR ] Failed to setup file logging: {e}")

logger = CustomLogger(_base_logger)


class DiscordWebhookHandler(logging.Handler):
    def __init__(self, webhook_url: str, ping_webhook: str | None = None, level: int = logging.NOTSET) -> None:
        super().__init__(level)
        self.webhook_url: str = webhook_url
        self.ping_webhook: str | None = ping_webhook
        self.message_queue = None
        self.worker_task = None
        self.shutdown_event = None
        try:
            self._start_worker()
        except Exception as e:
            print(f"[ ERROR ] Failed to setup Discord webhook handler: {e}")

    def _start_worker(self) -> None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                if self.message_queue is None:
                    self.message_queue = asyncio.Queue()
                if self.shutdown_event is None:
                    self.shutdown_event = asyncio.Event()
                if self.worker_task is None or self.worker_task.done():
                    self.worker_task = asyncio.create_task(self._worker())
            else:
                self.worker_task = None
        except RuntimeError:
            self.worker_task = None

    async def _worker(self) -> None:
        if self.shutdown_event is None or self.message_queue is None:
            return

        while not self.shutdown_event.is_set():
            try:
                content = await asyncio.wait_for(self.message_queue.get(), timeout=1.0)
                if content is None:
                    break

                webhook_sender.send(self.webhook_url, content)

                await asyncio.sleep(0.5)

                self.message_queue.task_done()

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[ ERROR ] Discord webhook worker error: {e}")

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno == logging.DEBUG and not config.debug_mode:
            return

        try:
            level_name = logging.getLevelName(record.levelno)
            asctime = datetime.fromtimestamp(record.created).strftime("%y/%m/%d %H:%M:%S")
            message = record.getMessage()

            ping_content = ""

            if config.ping_for_warnings:
                if self.ping_webhook and record.levelno >= logging.WARNING:
                    ping_content = f"{self.ping_webhook} "
            else:
                if self.ping_webhook and record.levelno >= logging.ERROR:
                    ping_content = f"{self.ping_webhook} "

            content = (
                f"{ping_content}\n"
                f"```\n"
                f"[ {level_name} ]    {message}    [{asctime} ({record.filename}:{record.funcName})]\n"
                f"```"
            )

            global _discord_webhook_send_count
            _discord_webhook_send_count += 1
            if _discord_webhook_send_count == 1:
                content = "_ _ \n_ _ \n_ _ \n" + content  # add newlines at the beginning of first log to separate logs

            if self.worker_task is None:
                self._start_worker()

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running() and self.message_queue is not None:
                    self.message_queue.put_nowait(content)
                else:
                    webhook_sender.send(self.webhook_url, content)
            except RuntimeError:
                webhook_sender.send(self.webhook_url, content)

        except Exception:
            # use print so i don't cause an infinite loop of errors
            print("[ ERROR ] Failed to queue log for Discord webhook!")

    def close(self) -> None:
        if self.shutdown_event is not None:
            self.shutdown_event.set()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running() and self.message_queue is not None:
                self.message_queue.put_nowait(None)
                if self.worker_task and not self.worker_task.done():
                    self.worker_task.cancel()
            elif self.message_queue is not None:
                asyncio.run(self.message_queue.put(None))
        except RuntimeError:
            pass
        super().close()


def _has_discord_handler(logr) -> bool:
    handlers = getattr(logr, 'handlers', [])
    for h in handlers:
        if isinstance(h, DiscordWebhookHandler):
            return True
    return False


if config.logger_webhook and not _has_discord_handler(logger):
    try:
        discord_handler = DiscordWebhookHandler(
            config.logger_webhook,
            f"<@{str(config.logger_webhook_ping)}>" if config.logger_webhook_ping else None
        )
        discord_handler.setLevel(setLevelValue)
        logger.addHandler(discord_handler)
    except Exception:
        logger.error("Failed to add Discord webhook handler to logger!")
        pass
