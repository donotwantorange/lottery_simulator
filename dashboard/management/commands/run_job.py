"""Worker entry point using exactly the application's Django settings."""

import logging
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "执行已接受的模拟任务快照（仅供服务端工作进程使用）"

    def add_arguments(self, parser):
        parser.add_argument("--job-dir", required=True, help="已接受任务的私有目录")

    def handle(self, *args, **options):
        from dashboard.services.runs import get_manager
        from dashboard.worker import run
        from dashboard.jobs import JobStateUnavailable

        manager = get_manager()
        directory = Path(options["job_dir"]).resolve()
        try:
            if (manager._job_dir(directory.name) != directory
                    or manager.get(directory.name) is None):
                raise CommandError("任务目录无效或不属于当前设置")
            logging.basicConfig(filename=directory / "worker.log", encoding="utf-8", level=logging.INFO)
            run(directory, Path(settings.DATABASES["default"]["NAME"]).resolve())
        except JobStateUnavailable as error:
            logging.getLogger(__name__).exception("Retaining job with unavailable state")
            raise CommandError("任务状态暂不可用，已保留恢复材料") from error
