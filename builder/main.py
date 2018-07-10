# Copyright 2014-present PlatformIO <contact@platformio.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from os.path import join, isdir
from time import sleep
from platform import system
from SCons.Script import (ARGUMENTS, COMMAND_LINE_TARGETS, AlwaysBuild,
                          Builder, Default, DefaultEnvironment)

from platformio.util import get_serialports



env = DefaultEnvironment()
platform = env.PioPlatform()

def BeforeUpload(target, source, env):  # pylint: disable=W0613,W0621

    if "program" in COMMAND_LINE_TARGETS:
        return

    upload_options = {}
    if "BOARD" in env:
        upload_options = env.BoardConfig().get("upload", {})

    # Deprecated: compatibility with old projects. Use `program` instead
    if "usb" in env.subst("$UPLOAD_PROTOCOL"):
        upload_options['require_upload_port'] = False
        env.Replace(UPLOAD_SPEED=None)

    if env.subst("$UPLOAD_SPEED"):
        env.Append(UPLOADERFLAGS=["-b", "$UPLOAD_SPEED"])

    # extra upload flags
    if "extra_flags" in upload_options:
        env.Append(UPLOADERFLAGS=upload_options.get("extra_flags"))

    # disable erasing by default
    env.Append(UPLOADERFLAGS=["-D"])

    if upload_options and not upload_options.get("require_upload_port", False):
        return

    env.AutodetectUploadPort()
    env.Append(UPLOADERFLAGS=["-P", '"$UPLOAD_PORT"'])

    if env.subst("$BOARD") in ("raspduino", "emonpi", "sleepypi"):

        def _rpi_sysgpio(path, value):
            with open(path, "w") as f:
                f.write(str(value))

        if env.subst("$BOARD") == "raspduino":
            pin_num = 18
        elif env.subst("$BOARD") == "sleepypi":
            pin_num = 22
        else:
            pin_num = 4

        _rpi_sysgpio("/sys/class/gpio/export", pin_num)
        _rpi_sysgpio("/sys/class/gpio/gpio%d/direction" % pin_num, "out")
        _rpi_sysgpio("/sys/class/gpio/gpio%d/value" % pin_num, 1)
        sleep(0.1)
        _rpi_sysgpio("/sys/class/gpio/gpio%d/value" % pin_num, 0)
        _rpi_sysgpio("/sys/class/gpio/unexport", pin_num)
    else:
        if not upload_options.get("disable_flushing", False) \
            and not env.get("UPLOAD_PORT", "").startswith("net:"):
            env.FlushSerialBuffer("$UPLOAD_PORT")

        before_ports = get_serialports()

        if upload_options.get("use_1200bps_touch", False):
            env.TouchSerialPort("$UPLOAD_PORT", 1200)

        if upload_options.get("wait_for_upload_port", False):
            env.Replace(UPLOAD_PORT=env.WaitForNewSerialPort(before_ports))
          
env.Replace(
    AR="arm-none-eabi-ar",
    AS="arm-none-eabi-as",
    CC="arm-none-eabi-gcc",
    GDB="arm-none-eabi-gdb",
    CXX="arm-none-eabi-g++",
    OBJCOPY="arm-none-eabi-objcopy",
    RANLIB="arm-none-eabi-gcc-ranlib",
    SIZETOOL="arm-none-eabi-size",

    ARFLAGS=["rcs"],

    ASFLAGS=["-c","-g","-w","-x", "assembler-with-cpp","-mthumb"],

    CFLAGS=[
        "-MMD"
    ],
    
    # both c and cpp
    CCFLAGS=[
        "-Os",  # optimize for size
        "-c",
        "-g",
        "-w", #disables compiler warnings
        "-nostdlib",
        "-Wall",  # show warnings
        "-ffunction-sections",  # place each function in its own section
        "-fdata-sections",      
        "-mthumb"
    ],

    CXXFLAGS=[
        "-fno-exceptions",
        "-fno-threadsafe-statics",
        "-fpermissive",
        "-mthumb"       
    ],

    CPPDEFINES=[("F_CPU", "$BOARD_F_CPU")],

    LINKFLAGS=[
        "-Os",
        "-nostartfiles",
        "-nostdlib",
        "-Wl,--gc-sections",
        "-mthumb",
        "--specs=nano.specs",
        "--specs=nosys.specs",
        "-Wl,-Map,"+join("$BUILD_DIR", "hi")+".map"
    ],

    LIBS=["m","gcc","c","stdc++"],
    
    PROGSUFFIX=".elf",
    
    FRAMEWORK_ARDUINOXMC_DIR=platform.get_package_dir(
        "framework-arduinoxmc"),
)

if "BOARD" in env:
    arm_math = "ARM_MATH_CM0"
    arm_dsp = ""
    if env.BoardConfig().get("build.variant")[-4] == '4':
        arm_math = "ARM_MATH_CM4"
        arm_dsp = "ARM_MATH_DSP"

    env.Append(
        CCFLAGS=[
            "-mcpu=%s" % env.BoardConfig().get("build.cpu")
        ],
        CPPDEFINES=[
            env.BoardConfig().get("build.family"),
            arm_dsp, # comment out if no DSP needed
            arm_math,
            "_INIT_DECLARATION_REQUIRED"
        ],
        LINKFLAGS=[
            "-mcpu=%s" % env.BoardConfig().get("build.cpu"),
            "-T"+join(platform.get_package_dir("framework-arduinoxmc"),"variants",env.BoardConfig().get("build.family"),"linker_script.ld")
        ],
        SIZEPRINTCMD='$SIZETOOL -B -d $SOURCES',
)
     
env.Append(
    CPPPATH = [
    ],
    
    ASFLAGS=env.get("CCFLAGS", [])[:],
    BUILDERS=dict(
        ElfToHex=Builder(
            action=env.VerboseAction(" ".join([
                "$OBJCOPY",
                "-O",
                "ihex",
                "$SOURCES",
                "$TARGET"
            ]), "Building $TARGET"),
            suffix=".hex"
        )
    )
)

#
# Target: Build executable and linkable firmware
#
target_elf = env.BuildProgram()

#
# Target: Print binary size
#
target_size = env.Alias(
    "size", target_elf,
    env.VerboseAction("$SIZEPRINTCMD", "Calculating size $SOURCE"))
AlwaysBuild(target_size)

#
# Target: Build the .hex file
#
target_hex = env.ElfToHex(join("$BUILD_DIR", "firmware"), target_elf)

#
# Target: Upload firmware
#
debug_tools = env.BoardConfig().get("debug.tools", {})
upload_protocol = env.subst("$UPLOAD_PROTOCOL")

def _jlink_cmd_script(env, source):
    print "SOURCE",source
    build_dir = env.subst("$BUILD_DIR")
    if not isdir(build_dir):
        makedirs(build_dir)
    script_path = join(build_dir, "upload.jlink")
    commands = ["setbmi 3","loadbin %s,0x08000000" % source, "r", "g","exit"]
    with open(script_path, "w") as fp:
        fp.write("\n".join(commands))
    return script_path

__jlink_cmd_script = _jlink_cmd_script(env, target_hex[0])    

env.Append(
    jlink_script = __jlink_cmd_script
)
print "script path", __jlink_cmd_script
env.Replace(
    UPLOADER="JLink.exe" if system() == "Windows" else "JLinkExe",
    UPLOADERFLAGS=[
        "-device", env.BoardConfig().get("debug", {}).get("jlink_device"),
        "-speed", "4000",
        "-if", "swd",
        "-autoconnect", "1"
    ],
    UPLOADCMD="$UPLOADER $UPLOADERFLAGS -CommanderScript $jlink_script"
)

upload_actions = [env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE")]
AlwaysBuild(env.Alias("upload", target_hex, upload_actions))

#
# Target: Define targets
#
Default([target_hex,target_size])