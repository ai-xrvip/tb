"""插件系统 —— 参考 chatgpt-on-wechat 的插件架构，支持热加载和生命周期管理"""
import os
import importlib
import inspect
from abc import ABC, abstractmethod
from typing import Optional
from utils.logger import logger


class PluginBase(ABC):
    """插件基类 —— 所有插件必须继承此类"""

    name: str = "base"
    version: str = "0.1.0"
    description: str = ""
    author: str = ""

    def __init__(self):
        self._enabled = False

    @abstractmethod
    async def on_enable(self):
        """插件启用时调用"""
        ...

    @abstractmethod
    async def on_disable(self):
        """插件禁用时调用"""
        ...

    async def on_message(self, update, context) -> Optional[bool]:
        """处理消息，返回 True 表示已处理（阻止后续处理）"""
        return False

    async def on_command(self, command: str, update, context) -> Optional[bool]:
        """处理命令"""
        return False

    def get_commands(self) -> list[dict]:
        """返回插件提供的命令列表 [{command, description, handler}]"""
        return []

    @property
    def is_enabled(self) -> bool:
        return self._enabled


class PluginManager:
    """插件管理器 —— 发现、加载、卸载插件"""

    def __init__(self, plugins_dir: str = "plugins"):
        self.plugins_dir = plugins_dir
        self._plugins: dict[str, PluginBase] = {}
        self._command_map: dict[str, tuple] = {}  # command -> (plugin, handler)

    def discover(self) -> list[str]:
        """发现所有可用插件"""
        available = []
        base_dir = os.path.join(os.path.dirname(__file__), "..", self.plugins_dir)
        base_dir = os.path.abspath(base_dir)

        if not os.path.isdir(base_dir):
            return available

        for item in os.listdir(base_dir):
            if item.startswith("_") or item.startswith("."):
                continue
            plugin_path = os.path.join(base_dir, item)
            if os.path.isdir(plugin_path) and os.path.exists(os.path.join(plugin_path, "__init__.py")):
                available.append(item)
            elif item.endswith(".py") and not item.startswith("_"):
                available.append(item[:-3])

        return available

    async def load_plugin(self, plugin_name: str) -> Optional[PluginBase]:
        """加载单个插件"""
        if plugin_name in self._plugins:
            return self._plugins[plugin_name]

        try:
            module = importlib.import_module(f"plugins.{plugin_name}")
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, PluginBase) and obj is not PluginBase:
                    plugin = obj()
                    plugin._enabled = True
                    await plugin.on_enable()
                    self._plugins[plugin_name] = plugin

                    # 注册命令
                    for cmd_info in plugin.get_commands():
                        cmd = cmd_info["command"]
                        handler = cmd_info.get("handler")
                        if cmd and handler:
                            self._command_map[cmd] = (plugin, handler)

                    logger.info(f"Plugin loaded: {plugin_name} v{plugin.version}")
                    return plugin
        except Exception as e:
            logger.error(f"Failed to load plugin {plugin_name}: {e}", exc_info=True)
        return None

    async def unload_plugin(self, plugin_name: str):
        """卸载插件"""
        plugin = self._plugins.pop(plugin_name, None)
        if plugin:
            await plugin.on_disable()
            # 移除命令
            self._command_map = {
                k: v for k, v in self._command_map.items()
                if v[0] is not plugin
            }
            logger.info(f"Plugin unloaded: {plugin_name}")

    async def load_all(self, enabled_list: list[str] = None):
        """加载所有或指定插件"""
        available = self.discover()
        to_load = enabled_list if enabled_list is not None else available
        for name in to_load:
            if name in available:
                await self.load_plugin(name)

    async def handle_message(self, update, context) -> bool:
        """让所有已启用插件处理消息"""
        for plugin in self._plugins.values():
            if plugin.is_enabled:
                try:
                    if await plugin.on_message(update, context):
                        return True
                except Exception as e:
                    logger.error(f"Plugin {plugin.name} on_message error: {e}")
        return False

    def get_plugin_command_handlers(self) -> dict:
        """获取所有插件命令处理器"""
        return dict(self._command_map)

    @property
    def loaded_plugins(self) -> list[str]:
        return list(self._plugins.keys())


# 全局单例
plugin_manager = PluginManager()
