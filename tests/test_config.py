"""验证源码与独立安装的数据目录选择，避免更换启动位置后读到另一份数据。"""

from pathlib import Path

from resume_maker.core import config


def test_source_data_directory_is_independent_of_working_directory(tmp_path, monkeypatch):
    """从其他目录启动源码安装时，仍使用源码项目的 data 目录。"""
    monkeypatch.delenv("RESUME_MAKER_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    expected = Path(config.__file__).resolve().parents[3] / "data"
    assert config.Config().data_dir == expected
    assert not (tmp_path / "data").exists()


def test_explicit_data_directory_overrides_environment(tmp_path, monkeypatch):
    """环境变量覆盖默认位置，显式配置进一步优先于环境变量。"""
    monkeypatch.setenv("RESUME_MAKER_DATA_DIR", str(tmp_path / "environment"))
    assert config.Config().data_dir == tmp_path / "environment"
    assert config.Config(data_dir=tmp_path / "explicit").data_dir == tmp_path / "explicit"


def test_installed_package_keeps_user_data_directory(tmp_path, monkeypatch):
    """独立安装包不向 site-packages 或当前项目目录写入个人数据。"""
    monkeypatch.delenv("RESUME_MAKER_DATA_DIR", raising=False)
    monkeypatch.setattr(
        config, "__file__", str(tmp_path / "site-packages/resume_maker/core/config.py")
    )
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "another-project"\n')
    assert config.Config().data_dir == Path.home() / ".resume-maker"
