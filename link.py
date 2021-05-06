import copy
import platform

from platformio.managers.platform import PlatformBase
from platformio.util import get_systype


class P33Platform(PlatformBase):

    def is_embedded(self):
        return True

    def configure_default_packages(self, variables, targets):
        if variables.get("board"):
            upload_protocol = variables.get("upload_protocol",
                                            self.board_config(
                                                variables.get("board")).get(
                                                    "upload.protocol", ""))
            if upload_protocol == "cmsis-dap":
                self.packages['tool-pyocd']['type'] = "uploader"

        frameworks = variables.get("pioframework", [])
        if "mbed" in frameworks:
            self.packages["toolchain-gccarmnoneeabi"]["version"] = "~1.90201.0"
        if "zephyr" in frameworks:
            for p in self.packages:
                if p.startswith("framework-zephyr-") or p in (
                    "tool-cmake", "tool-dtc", "tool-ninja"):
                    self.packages[p]["optional"] = False
            if "windows" not in get_systype():
                self.packages["tool-gperf"]["optional"] = False

        # configure J-LINK tool
        jlink_conds = [
            "jlink" in variables.get(option, "")
            for option in ("upload_protocol", "debug_tool")
        ]
        if variables.get("board"):
            board_config = self.board_config(variables.get("board"))
            jlink_conds.extend([
                "jlink" in board_config.get(key, "")
                for key in ("debug.default_tools", "upload.protocol")
            ])
        jlink_pkgname = "tool-jlink"
        if not any(jlink_conds) and jlink_pkgname in self.packages:
            del self.packages[jlink_pkgname]

        return PlatformBase.configure_default_packages(self, variables,
                                                       targets)

    def get_boards(self, id_=None):
        result = PlatformBase.get_boards(self, id_)
        if not result:
            return result
        if id_:
            return self._add_default_debug_tools(result)
        else:
            for key, value in result.items():
                result[key] = self._add_default_debug_tools(result[key])
        return result

    def _add_default_debug_tools(self, board):
        debug = board.manifest.get("debug", {})
        upload_protocols = board.manifest.get("upload", {}).get(
            "protocols", [])
        if "tools" not in debug:
            debug["tools"] = {}

        # J-Link / BlackMagic Probe
        for link in ("blackmagic", "cmsis-dap", "jlink"):
            if link not in upload_protocols or link in debug["tools"]:
                continue

            if link == "blackmagic":
                debug["tools"]["blackmagic"] = {
                    "hwids": [["0x1d50", "0x6018"]],
                    "require_debug_port": True
                }

            elif link == "cmsis-dap":
                if debug.get("pyocd_target"):
                    pyocd_target = debug.get("pyocd_target")
                    assert pyocd_target
                    debug["tools"][link] = {
                        "onboard": True,
                        "server": {
                            "package": "tool-pyocd",
                            "executable": "$PYTHONEXE",
                            "arguments": [
                                "pyocd-gdbserver.py",
                                "-t",
                                pyocd_target
                            ],
                            "ready_pattern": "GDB server started on port"
                        }
                    }
                else:
                    openocd_target = debug.get("openocd_target")
                    assert openocd_target
                    debug["tools"][link] = {
                        "load_cmd": "preload",
                        "onboard": True,
                        "server": {
                            "executable": "bin/openocd",
                            "package": "tool-openocd",
                            "arguments": [
                                "-s", "$PACKAGE_DIR/scripts",
                                "-f", "interface/cmsis-dap.cfg",
                                "-f", "target/%s.cfg" % openocd_target
                            ]
                        }
                    }

            elif link == "jlink":
                assert debug.get("jlink_device"), (
                    "Missed J-Link Device ID for %s" % board.id)
                debug["tools"][link] = {
                    "server": {
                        "package": "tool-jlink",
                        "arguments": [
                            "-singlerun",
                            "-if", "SWD",
                            "-select", "USB",
                            "-device", debug.get("jlink_device"),
                            "-port", "2331"
                        ],
                        "executable": ("JLinkGDBServerCL.exe"
                                       if platform.system() == "Windows" else
                                       "JLinkGDBServer")
                    },
                    "onboard": link in debug.get("onboard_tools", [])
                }

        board.manifest["debug"] = debug
        return board

    def configure_debug_options(self, initial_debug_options, ide_data):
        debug_options = copy.deepcopy(initial_debug_options)
        adapter_speed = initial_debug_options.get("speed")
        if adapter_speed:
            server_options = debug_options.get("server") or {}
            server_executable = server_options.get("executable", "").lower()
            if "openocd" in server_executable:
                debug_options["server"]["arguments"].extend(
                    ["-c", "adapter speed %s" % adapter_speed]
                )
            elif "jlink" in server_executable:
                debug_options["server"]["arguments"].extend(
                    ["-speed", adapter_speed]
                )

        return debug_options
