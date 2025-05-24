import zipfile
from pathlib import Path
from django.http import HttpResponse

from value_investment.value_investment.utils.utils import logger_create

logger = logger_create(__name__)

def zip_response(file_paths, zip_name):
    response = HttpResponse(content_type="application/zip")
    response["Content-Disposition"] = f"attachment; filename={zip_name}"

    try:
        with zipfile.ZipFile(response, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            for path in file_paths:
                if Path(path).is_file():
                    zip_file.write(path, Path(path).name)
                    logger.info(f"壓縮檔案: {path}")
                else:
                    logger.warning(f"檔案不存在: {path}")
        return response
    except Exception as e:
        logger.error(f"壓縮檔案失敗: {str(e)}")
        return HttpResponse("壓縮檔案失敗", status=500)