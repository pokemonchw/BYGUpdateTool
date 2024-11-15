import sys
import os
import requests
import zipfile
import tempfile
import json
import shutil
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLabel, QMessageBox,
    QProgressBar, QHBoxLayout, QListWidget, QListWidgetItem, QComboBox,
    QTextEdit, QLineEdit, QMenu, QTabWidget
)
from PySide6.QtCore import Qt, QThread, Signal
import subprocess
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import certifi

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CURRENT_VERSION = ""

class UpdateChecker(QThread):
    """ 更新检查器 """
    releases_fetched = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, session, repo, github_api_token):
        """
        初始化 UpdateChecker 线程
        Keyword arguments:
        session -- requests.Session 对象，用于发送网络请求
        repo -- 仓库地址，格式为 'owner/repository'
        github_api_token -- GitHub API 令牌，用于授权访问 GitHub API
        """
        super().__init__()
        self.session = session
        self.repo = repo
        self.github_api_token = github_api_token

    def run(self):
        """ 线程运行函数，获取仓库的所有发布版本信息 """
        headers = {'Accept': 'application/vnd.github.v3+json'}
        if self.github_api_token:
            headers["Authorization"] = f"token {self.github_api_token}"
        try:
            response = self.session.get(
                f"https://api.github.com/repos/{self.repo}/releases?per_page=100",
                headers=headers
            )
            response.raise_for_status()
            releases = response.json()
            self.releases_fetched.emit(releases)
        except requests.RequestException as e:
            error_message = f"获取更新信息时出错: {e}"
            print(error_message)
            self.error_occurred.emit(error_message)

class Updater(QThread):
    """ 更新下载器 """
    progress = Signal(int)
    finished = Signal(bool)
    error_occurred = Signal(str)

    def __init__(self, session, download_url, extract_path, asset_name, github_api_token):
        """
        初始化 Updater 线程
        Keyword arguments:
        session -- requests.Session 对象，用于发送网络请求
        download_url -- 要下载的文件的 URL
        extract_path -- 文件解压的目标路径
        asset_name -- 资产文件名
        github_api_token -- GitHub API 令牌，用于授权访问 GitHub API
        """
        super().__init__()
        self.session = session
        self.download_url = download_url
        self.extract_path = extract_path
        self.asset_name = asset_name
        self.github_api_token = github_api_token

    def run(self):
        """ 线程运行函数，下载并解压指定的资产文件 """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': '*/*'
            }
            if self.github_api_token:
                headers["Authorization"] = f"token {self.github_api_token}"
            response = self.session.get(
                self.download_url, stream=True, timeout=60, headers=headers, allow_redirects=False
            )
            if response.status_code in (301, 302, 303, 307, 308):
                redirect_url = response.headers.get('Location')
                if redirect_url:
                    response = self.session.get(
                        redirect_url, stream=True, timeout=60, headers={'User-Agent': 'Mozilla/5.0'}
                    )
                    response.raise_for_status()
                else:
                    error_message = "无法获取重定向后的下载链接"
                    print(error_message)
                    self.error_occurred.emit(error_message)
                    self.finished.emit(False)
                    return
            else:
                response.raise_for_status()
            content_type = response.headers.get('Content-Type', '')
            if 'application/zip' not in content_type and 'application/octet-stream' not in content_type:
                error_message = f"下载的文件不是 ZIP 文件，Content-Type: {content_type}"
                print(error_message)
                self.error_occurred.emit(error_message)
                self.finished.emit(False)
                return
            total_length = int(response.headers.get("content-length", 0))
            download_path = os.path.join(tempfile.gettempdir(), self.asset_name)
            with open(download_path, "wb") as file:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        file.write(chunk)
                        downloaded += len(chunk)
                        if total_length > 0:
                            self.progress.emit(int((downloaded / total_length) * 100))
                        else:
                            self.progress.emit(0)
            if not zipfile.is_zipfile(download_path):
                error_message = "下载的文件不是有效的 ZIP 文件"
                print(error_message)
                self.error_occurred.emit(error_message)
                self.finished.emit(False)
                return
            import re
            asset_name_without_ext = os.path.splitext(self.asset_name)[0]
            safe_folder_name = re.sub(r'[\\/:"*?<>|]+', "_", asset_name_without_ext)
            folder_path = os.path.join(self.extract_path, safe_folder_name)
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)
            else:
                shutil.rmtree(folder_path)
                os.makedirs(folder_path)
            with zipfile.ZipFile(download_path, 'r') as zip_ref:
                zip_ref.extractall(folder_path)
            self.finished.emit(True)
        except requests.RequestException as e:
            error_message = f"下载更新时出错: {e}"
            print(error_message)
            self.error_occurred.emit(error_message)
            self.finished.emit(False)

class APIUpdateChecker(QThread):
    """ API 更新检查器 """
    releases_fetched = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, session, api_base_url):
        """
        初始化 APIUpdateChecker 线程
        Keyword arguments:
        session -- requests.Session 对象，用于发送网络请求
        api_base_url -- API 基础 URL
        """
        super().__init__()
        self.session = session
        self.api_base_url = api_base_url

    def run(self):
        """ 线程运行函数，获取 API 的所有发布版本信息 """
        try:
            response = self.session.get(f"{self.api_base_url}/api/v1/version/getHistory")
            response.raise_for_status()
            data = response.json()
            if data.get('success'):
                releases = data.get('result', [])
                self.releases_fetched.emit(releases)
            else:
                error_message = data.get('message', '未知错误')
                print(error_message)
                self.error_occurred.emit(error_message)
        except requests.RequestException as e:
            error_message = f"获取更新信息时出错: {e}"
            print(error_message)
            self.error_occurred.emit(error_message)

class APIUpdater(QThread):
    """ API 更新下载器 """
    progress = Signal(int)
    finished = Signal(bool)
    error_occurred = Signal(str)

    def __init__(self, session, download_url, extract_path, asset_name):
        """
        初始化 APIUpdater 线程
        Keyword arguments:
        session -- requests.Session 对象，用于发送网络请求
        download_url -- 要下载的文件的 URL
        extract_path -- 文件解压的目标路径
        asset_name -- 资产文件名
        """
        super().__init__()
        self.session = session
        self.download_url = download_url
        self.extract_path = extract_path
        self.asset_name = asset_name

    def run(self):
        """ 线程运行函数，下载并解压指定的资产文件 """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': '*/*'
            }
            response = self.session.get(
                self.download_url, stream=True, timeout=60, headers=headers
            )
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '')
            if 'application/zip' not in content_type and 'application/octet-stream' not in content_type:
                error_message = f"下载的文件不是 ZIP 文件，Content-Type: {content_type}"
                print(error_message)
                self.error_occurred.emit(error_message)
                self.finished.emit(False)
                return
            total_length = int(response.headers.get("content-length", 0))
            download_path = os.path.join(tempfile.gettempdir(), self.asset_name)
            with open(download_path, "wb") as file:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        file.write(chunk)
                        downloaded += len(chunk)
                        if total_length > 0:
                            self.progress.emit(int((downloaded / total_length) * 100))
                        else:
                            self.progress.emit(0)
            if not zipfile.is_zipfile(download_path):
                error_message = "下载的文件不是有效的 ZIP 文件"
                print(error_message)
                self.error_occurred.emit(error_message)
                self.finished.emit(False)
                return
            import re
            asset_name_without_ext = os.path.splitext(self.asset_name)[0]
            safe_folder_name = re.sub(r'[\\/:"*?<>|]+', "_", asset_name_without_ext)
            folder_path = os.path.join(self.extract_path, safe_folder_name)
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)
            else:
                shutil.rmtree(folder_path)
                os.makedirs(folder_path)
            with zipfile.ZipFile(download_path, 'r') as zip_ref:
                zip_ref.extractall(folder_path)
            self.finished.emit(True)
        except requests.RequestException as e:
            error_message = f"下载更新时出错: {e}"
            print(error_message)
            self.error_occurred.emit(error_message)
            self.finished.emit(False)

class UpdaterUI(QWidget):
    """ 主界面 """

    def __init__(self):
        """ 初始化主界面 """
        super().__init__()
        self.setWindowTitle("更新器")
        self.setGeometry(200, 200, 800, 600)
        self.layout = QVBoxLayout()
        self.config = self.load_config()
        self.repositories = self.config.get("repositories", [])
        self.github_api_token = self.config.get("github_api_token", "")
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount('https://', adapter)
        self.session.verify = True
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
        self.tab_widget = QTabWidget()
        self.layout.addWidget(self.tab_widget)
        for repo_info in self.repositories:
            repo_name = repo_info.get("name", "未知仓库")
            repo_address = repo_info.get("repo", "")
            tab = self.create_repo_tab(repo_name, repo_address)
            self.tab_widget.addTab(tab, repo_name)
        # 创建API下载的标签页
        self.api_tab = self.create_api_tab()
        self.tab_widget.addTab(self.api_tab, "dieloli")
        self.game_list = QListWidget()
        self.game_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.game_list.customContextMenuRequested.connect(self.show_context_menu)
        self.layout.addWidget(self.game_list)
        self.populate_game_list()
        self.game_list.itemDoubleClicked.connect(self.on_game_double_clicked)
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        self.setLayout(self.layout)

    def load_config(self):
        """
        加载配置文件 config.json
        Return arguments:
        dict -- 配置文件内容的字典
        """
        config_path = os.path.join(os.getcwd(), "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding='utf-8') as f:
                    config = json.load(f)
                    return config
            except Exception as e:
                print(f"读取配置文件出错: {e}")
                return {}
        else:
            print("未找到配置文件，使用默认配置")
            return {}

    def create_repo_tab(self, repo_name, repo_address):
        """
        创建仓库的标签页
        Keyword arguments:
        repo_name -- 仓库显示名称
        repo_address -- 仓库地址，格式为 'owner/repository'
        Return arguments:
        QWidget -- 包含仓库信息和操作控件的标签页小部件
        """
        tab = QWidget()
        tab_layout = QVBoxLayout()
        repo_label = QLabel(f"仓库地址: {repo_address}")
        tab_layout.addWidget(repo_label)
        check_update_button = QPushButton("检查更新")
        check_update_button.clicked.connect(lambda: self.check_for_updates(repo_address, repo_name, tab))
        tab_layout.addWidget(check_update_button)
        version_selector = QComboBox()
        version_selector.setVisible(False)
        tab_layout.addWidget(version_selector)
        asset_selector = QComboBox()
        asset_selector.setVisible(False)
        tab_layout.addWidget(asset_selector)
        release_notes = QTextEdit()
        release_notes.setReadOnly(True)
        release_notes.setVisible(False)
        tab_layout.addWidget(release_notes)
        download_button = QPushButton("下载并更新")
        download_button.setVisible(False)
        tab_layout.addWidget(download_button)
        progress_bar = QProgressBar()
        progress_bar.setValue(0)
        progress_bar.setVisible(False)
        tab_layout.addWidget(progress_bar)
        tab.repo_name = repo_name
        tab.repo_address = repo_address
        tab.check_update_button = check_update_button
        tab.version_selector = version_selector
        tab.asset_selector = asset_selector
        tab.release_notes = release_notes
        tab.download_button = download_button
        tab.progress_bar = progress_bar
        tab.setLayout(tab_layout)
        return tab

    def create_api_tab(self):
        """
        创建API更新的标签页
        Return arguments:
        QWidget -- 包含API更新信息和操作控件的标签页小部件
        """
        tab = QWidget()
        tab_layout = QVBoxLayout()
        check_update_button = QPushButton("检查更新")
        check_update_button.clicked.connect(lambda: self.api_check_for_updates(tab))
        tab_layout.addWidget(check_update_button)
        version_selector = QComboBox()
        version_selector.setVisible(False)
        tab_layout.addWidget(version_selector)
        asset_selector = QComboBox()
        asset_selector.setVisible(False)
        tab_layout.addWidget(asset_selector)
        release_notes = QTextEdit()
        release_notes.setReadOnly(True)
        release_notes.setVisible(False)
        tab_layout.addWidget(release_notes)
        download_button = QPushButton("下载并更新")
        download_button.setVisible(False)
        tab_layout.addWidget(download_button)
        progress_bar = QProgressBar()
        progress_bar.setValue(0)
        progress_bar.setVisible(False)
        tab_layout.addWidget(progress_bar)
        tab.check_update_button = check_update_button
        tab.version_selector = version_selector
        tab.asset_selector = asset_selector
        tab.release_notes = release_notes
        tab.download_button = download_button
        tab.progress_bar = progress_bar
        tab.setLayout(tab_layout)
        return tab

    def populate_game_list(self):
        """ 填充游戏列表，显示当前仓库下已下载的游戏版本 """
        self.game_list.clear()
        current_tab = self.tab_widget.currentWidget()
        if hasattr(current_tab, 'repo_name'):
            repo_name = current_tab.repo_name
        else:
            repo_name = "API更新"
        game_path = os.path.join(os.getcwd(), "game", repo_name)
        if not os.path.exists(game_path):
            os.makedirs(game_path)
        for folder_name in os.listdir(game_path):
            folder_path = os.path.join(game_path, folder_name)
            if os.path.isdir(folder_path):
                list_item = QListWidgetItem()
                list_item.setData(Qt.UserRole, folder_path)
                widget = QWidget()
                h_layout = QHBoxLayout()
                name_label = QLabel(folder_name)
                h_layout.addWidget(name_label)
                h_layout.setContentsMargins(10, 5, 10, 5)
                h_layout.setSpacing(20)
                widget.setLayout(h_layout)
                list_item.setSizeHint(widget.sizeHint())
                self.game_list.addItem(list_item)
                self.game_list.setItemWidget(list_item, widget)

    def get_version_info(self, path):
        """
        获取指定路径下的游戏版本信息
        Keyword arguments:
        path -- 游戏文件夹的路径
        Return arguments:
        str -- 游戏版本信息，如果无法获取则返回 '未知'
        """
        package_json_path = os.path.join(path, "package.json")
        if os.path.exists(package_json_path):
            with open(package_json_path, "r", encoding='utf-8') as f:
                package_data = json.load(f)
                return package_data.get("version", "未知")
        return "未知"

    def show_context_menu(self, position):
        """
        显示游戏列表项的右键菜单
        Keyword arguments:
        position -- 鼠标右键点击的位置
        """
        item = self.game_list.itemAt(position)
        if item:
            menu = QMenu()
            start_action = menu.addAction("启动")
            delete_action = menu.addAction("删除")
            action = menu.exec_(self.game_list.viewport().mapToGlobal(position))
            if action == start_action:
                self.start_game(item.data(Qt.UserRole))
            elif action == delete_action:
                self.delete_game(item.data(Qt.UserRole))

    def start_game(self, path):
        """
        启动指定路径下的游戏
        Keyword arguments:
        path -- 游戏文件夹的路径
        """
        game_exe_path = os.path.join(path, "game.exe")
        if os.path.exists(game_exe_path):
            try:
                subprocess.Popen([game_exe_path], cwd=path)
            except Exception as e:
                QMessageBox.critical(self, "启动失败", f"无法启动游戏: {e}")
        else:
            QMessageBox.warning(self, "文件不存在", f"未找到 {game_exe_path}")

    def on_game_double_clicked(self, item):
        """
        双击游戏列表项时的处理函数，启动游戏
        Keyword arguments:
        item -- 被双击的 QListWidgetItem 项目
        """
        path = item.data(Qt.UserRole)
        self.start_game(path)

    def delete_game(self, path):
        """
        删除指定路径下的游戏
        Keyword arguments:
        path -- 游戏文件夹的路径
        """
        reply = QMessageBox.question(self, "删除游戏", f"确定要删除 {os.path.basename(path)} 吗",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                shutil.rmtree(path)
                self.populate_game_list()
            except Exception as e:
                QMessageBox.critical(self, "错误", f"无法删除 {os.path.basename(path)}: {e}")

    def check_for_updates(self, repo_address, repo_name, tab):
        """
        检查指定仓库的更新。
        Keyword arguments:
        repo_address -- 仓库地址，格式为 'owner/repository'
        repo_name -- 仓库显示名称
        tab -- 仓库对应的标签页小部件
        """
        if not repo_address:
            QMessageBox.critical(self, "错误", "仓库地址无效")
            return
        tab.check_update_button.setEnabled(False)
        label = QLabel("正在检查更新...")
        label.setAlignment(Qt.AlignCenter)
        tab.layout().addWidget(label)
        checker_thread = UpdateChecker(self.session, repo_address, self.github_api_token)
        checker_thread.releases_fetched.connect(lambda releases: self.show_releases(releases, repo_name, tab))
        checker_thread.error_occurred.connect(self.show_error_message)
        checker_thread.start()
        tab.checker_thread = checker_thread

    def show_releases(self, releases, repo_name, tab):
        """
        显示仓库的发布版本信息
        Keyword arguments:
        releases -- 发布版本的列表
        repo_name -- 仓库显示名称
        tab -- 仓库对应的标签页小部件
        """
        tab.check_update_button.setEnabled(True)
        if not releases:
            QMessageBox.warning(self, "警告", "未找到任何发布版本")
            return
        tab.version_selector.clear()
        for release in releases:
            version_tag = release["tag_name"]
            tab.version_selector.addItem(version_tag, release)
        tab.version_selector.setVisible(True)
        tab.release_notes.setVisible(True)
        tab.download_button.setVisible(True)
        tab.version_selector.currentIndexChanged.connect(lambda index: self.display_release_details(index, tab))
        for i in reversed(range(tab.layout().count())):
            widget = tab.layout().itemAt(i).widget()
            if isinstance(widget, QLabel) and widget.text() == "正在检查更新...":
                tab.layout().removeWidget(widget)
                widget.deleteLater()
        tab.download_button.clicked.connect(lambda: self.start_update(repo_name, tab))
        self.display_release_details(0, tab)

    def display_release_details(self, index, tab):
        """
        显示选定版本的发布说明和资产列表
        Keyword arguments:
        index -- 版本选择器中选定的索引
        tab -- 仓库对应的标签页小部件
        """
        release = tab.version_selector.itemData(index)
        if release:
            tab.release_notes.setText(release.get("body", "没有发布说明"))
            tab.selected_release = release
            assets = release.get("assets", [])
            tab.asset_selector.clear()
            if assets:
                for asset in assets:
                    tab.asset_selector.addItem(asset['name'], asset)
                tab.asset_selector.setVisible(True)
            else:
                tab.asset_selector.setVisible(False)
                QMessageBox.warning(self, "警告", "该版本没有可用的资产文件")

    def get_real_download_url(self, url):
        # You can modify this method if needed based on your requirements
        return url

    def start_update(self, repo_name, tab):
        """
        开始下载并更新选定的资产文件
        Keyword arguments:
        repo_name -- 仓库显示名称
        tab -- 仓库对应的标签页小部件
        """
        selected_asset_index = tab.asset_selector.currentIndex()
        if selected_asset_index == -1:
            QMessageBox.warning(self, "警告", "请先选择要下载的资产文件")
            return
        asset = tab.asset_selector.itemData(selected_asset_index)
        download_url = asset.get("browser_download_url")
        download_url = self.get_real_download_url(download_url)
        asset_name = asset.get("name")
        if not download_url or not asset_name:
            QMessageBox.warning(self, "警告", "无法获取资产文件的下载链接或文件名")
            return
        tab.progress_bar.setVisible(True)
        game_path = os.path.join(os.getcwd(), "game", repo_name)
        updater_thread = Updater(self.session, download_url, game_path, asset_name, self.github_api_token)
        updater_thread.progress.connect(tab.progress_bar.setValue)
        updater_thread.finished.connect(lambda success: self.update_finished(success, tab))
        updater_thread.error_occurred.connect(self.show_error_message)
        updater_thread.start()
        tab.updater_thread = updater_thread

    def update_finished(self, success, tab):
        """
        更新完成后的处理函数
        Keyword arguments:
        success -- 布尔值，表示更新是否成功
        tab -- 仓库对应的标签页小部件
        """
        tab.check_update_button.setEnabled(True)
        if success:
            QMessageBox.information(self, "更新完成", "应用程序已成功更新")
            self.populate_game_list()
        else:
            QMessageBox.critical(self, "更新失败", "更新应用程序时发生错误")
        tab.progress_bar.setVisible(False)

    def show_error_message(self, message):
        """
        显示错误信息。
        Keyword arguments:
        message -- 错误信息字符串。
        """
        QMessageBox.critical(self, "错误", message)

    def on_tab_changed(self, index):
        """
        标签页切换时的处理函数，刷新游戏列表。
        Keyword arguments:
        index -- 当前选中的标签页索引。
        """
        self.populate_game_list()

    # 以下是新增的 API 更新相关方法
    def api_check_for_updates(self, tab):
        """
        检查 API 的更新。
        Keyword arguments:
        tab -- API 对应的标签页小部件
        """
        api_base_url = self.config.get("api_base_url", "")
        if not api_base_url:
            QMessageBox.critical(self, "错误", "API 基础 URL 无效")
            return
        tab.check_update_button.setEnabled(False)
        label = QLabel("正在检查更新...")
        label.setAlignment(Qt.AlignCenter)
        tab.layout().addWidget(label)
        checker_thread = APIUpdateChecker(self.session, api_base_url)
        checker_thread.releases_fetched.connect(lambda releases: self.api_show_releases(releases, tab))
        checker_thread.error_occurred.connect(self.show_error_message)
        checker_thread.start()
        tab.checker_thread = checker_thread

    def api_show_releases(self, releases, tab):
        """
        显示 API 的发布版本信息
        Keyword arguments:
        releases -- 发布版本的列表
        tab -- API 对应的标签页小部件
        """
        tab.check_update_button.setEnabled(True)
        if not releases:
            QMessageBox.warning(self, "警告", "未找到任何发布版本")
            return
        tab.version_selector.clear()
        for release in releases:
            version_name = release.get("versionName")
            tab.version_selector.addItem(version_name, release)
        tab.version_selector.setVisible(True)
        tab.release_notes.setVisible(True)
        tab.download_button.setVisible(True)
        tab.version_selector.currentIndexChanged.connect(lambda index: self.api_display_release_details(index, tab))
        for i in reversed(range(tab.layout().count())):
            widget = tab.layout().itemAt(i).widget()
            if isinstance(widget, QLabel) and widget.text() == "正在检查更新...":
                tab.layout().removeWidget(widget)
                widget.deleteLater()
        tab.download_button.clicked.connect(lambda: self.api_start_update(tab))
        self.api_display_release_details(0, tab)

    def api_display_release_details(self, index, tab):
        """
        显示选定版本的发布说明和资产列表
        Keyword arguments:
        index -- 版本选择器中选定的索引
        tab -- API 对应的标签页小部件
        """
        release = tab.version_selector.itemData(index)
        if release:
            release_info = f"版本: {release.get('versionName')}\n作者: {release.get('author')}\n提交: {release.get('commit')}\n创建时间: {release.get('createTime')}"
            tab.release_notes.setText(release_info)
            tab.selected_release = release
            assets = release.get("releaseFile", [])
            tab.asset_selector.clear()
            if assets:
                for asset in assets:
                    platform = asset.get('platform')
                    size = asset.get('size')
                    asset_name = f"{platform} ({size})"
                    tab.asset_selector.addItem(asset_name, asset)
                tab.asset_selector.setVisible(True)
            else:
                tab.asset_selector.setVisible(False)
                QMessageBox.warning(self, "警告", "该版本没有可用的资产文件")

    def api_start_update(self, tab):
        """
        开始下载并更新选定的资产文件
        Keyword arguments:
        tab -- API 对应的标签页小部件
        """
        selected_asset_index = tab.asset_selector.currentIndex()
        if selected_asset_index == -1:
            QMessageBox.warning(self, "警告", "请先选择要下载的资产文件")
            return
        asset = tab.asset_selector.itemData(selected_asset_index)
        download_url = asset.get("downloadUrl")
        asset_name = download_url.split('/')[-1]  # 从 URL 中获取文件名
        if not download_url or not asset_name:
            QMessageBox.warning(self, "警告", "无法获取资产文件的下载链接或文件名")
            return
        tab.progress_bar.setVisible(True)
        game_path = os.path.join(os.getcwd(), "game", "API更新")
        updater_thread = APIUpdater(self.session, download_url, game_path, asset_name)
        updater_thread.progress.connect(tab.progress_bar.setValue)
        updater_thread.finished.connect(lambda success: self.api_update_finished(success, tab))
        updater_thread.error_occurred.connect(self.show_error_message)
        updater_thread.start()
        tab.updater_thread = updater_thread

    def api_update_finished(self, success, tab):
        """
        API 更新完成后的处理函数
        Keyword arguments:
        success -- 布尔值，表示更新是否成功
        tab -- API 对应的标签页小部件
        """
        tab.check_update_button.setEnabled(True)
        if success:
            QMessageBox.information(self, "更新完成", "应用程序已成功更新")
            self.populate_game_list()
        else:
            QMessageBox.critical(self, "更新失败", "更新应用程序时发生错误")
        tab.progress_bar.setVisible(False)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = UpdaterUI()
    window.show()
    sys.exit(app.exec())

