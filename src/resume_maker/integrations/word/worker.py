"""在独立子进程中驱动 Word，使渲染可超时回收且不阻塞 API 工作线程。"""

import json
import sys
from pathlib import Path

import psutil


def main():
    """创建独立 Word COM 实例，登记进程身份并导出 PDF，最后释放文档与 COM。"""
    import pythoncom
    import win32com.client
    import win32process

    pythoncom.CoInitialize()
    application = document = None
    update_links = None
    try:
        existing = {
            p.pid
            for p in psutil.process_iter(["name"])
            if (p.info["name"] or "").lower() == "winword.exe"
        }
        application = win32com.client.DispatchEx("Word.Application")
        application.Visible = False
        application.DisplayAlerts = 0
        application.AutomationSecurity = 3
        update_links = application.Options.UpdateLinksAtOpen
        application.Options.UpdateLinksAtOpen = False
        # 通过文档窗口取得 HWND，再核验独立 Word 实例的进程身份。
        document = application.Documents.Add()
        _, pid = win32process.GetWindowThreadProcessId(document.Windows(1).Hwnd)
        if pid in existing:
            document.Close(False)
            document = None
            application = None
            raise RuntimeError("Word 未创建独立渲染实例，请稍后重试。")
        Path(sys.argv[3]).write_text(
            json.dumps({"pid": pid, "created": psutil.Process(pid).create_time()})
        )
        document.Close(False)
        document = None
        document = application.Documents.Open(
            sys.argv[1],
            ReadOnly=True,
            AddToRecentFiles=False,
            ConfirmConversions=False,
            OpenAndRepair=True,
            PasswordDocument="resume-maker-no-password",
        )
        if len(sys.argv) > 4 and sys.argv[4] == "convert":
            document.AcceptAllRevisions()
            document.SaveAs2(sys.argv[2], FileFormat=16, AddToRecentFiles=False)
        else:
            document.Repaginate()
            document.ExportAsFixedFormat(sys.argv[2], 17)
    finally:
        if document is not None:
            document.Close(False)
        if application is not None:
            try:
                if update_links is not None:
                    application.Options.UpdateLinksAtOpen = update_links
            finally:
                application.Quit()
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
