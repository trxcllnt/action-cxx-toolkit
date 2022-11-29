#!/usr/bin/env python3

import os, subprocess

ubuntu_versions={
    "20.04": {
        "clang_versions": list(range(7, 15 + 1)) + ["dev"],
        "gcc_versions": list(range(7, 11 + 1)),
        "nvcc_versions": ["11.7.1", "11.8.0"],
        "nvhpc_versions": [
            { "hpc_ver": "22.7", "cuda_ver": "11.7"},
            { "hpc_ver": "22.7", "cuda_ver": "_multi"},
            { "hpc_ver": "22.9", "cuda_ver": "11.7"},
            { "hpc_ver": "22.9", "cuda_ver": "_multi"},
            { "hpc_ver": "22.11", "cuda_ver": "11.8"},
            { "hpc_ver": "22.11", "cuda_ver": "_multi"},
        ],
    },
    "22.04": {
        "clang_versions": list(range(14, 15 + 1)) + ["dev"],
        "gcc_versions": list(range(9, 12 + 1)),
        "nvcc_versions": ["11.7.1", "11.8.0"],
        "nvhpc_versions": [
            { "hpc_ver": "22.7", "cuda_ver": "11.7"},
            { "hpc_ver": "22.7", "cuda_ver": "_multi"},
            { "hpc_ver": "22.9", "cuda_ver": "11.7"},
            { "hpc_ver": "22.9", "cuda_ver": "_multi"},
            { "hpc_ver": "22.11", "cuda_ver": "11.8"},
            { "hpc_ver": "22.11", "cuda_ver": "_multi"},
        ],
    },
}

prologue = """

ARG DEBIAN_FRONTEND=noninteractive
ARG CMAKE_VERSION=3.24.2

SHELL ["/bin/bash", "-Eeox", "pipefail", "-c"]
"""

install_base = """
# Common package setup
RUN set -xe; \\
    # Install pacakges to allow us to install other packages
    apt update; \\
    apt install -y --no-install-recommends \\
        apt-transport-https ca-certificates gnupg software-properties-common wget; \\
    apt-add-repository -y -n 'ppa:ubuntu-toolchain-r/test'; \\
    apt update; \\
    # Install generic build tools & python
    apt install -y --no-install-recommends \\
        pkg-config make \\
        python3 python3-pip python3-setuptools \\
        ; \\
    # Install CMake
    wget -O /tmp/cmake.sh \\
        https://github.com/Kitware/CMake/releases/download/v${CMAKE_VERSION}/cmake-${CMAKE_VERSION}-linux-$(uname -m).sh; \\
    sh /tmp/cmake.sh --skip-license --exclude-subdir --prefix=/usr/local; \\
    # Cleanup apt packages
    rm -rf /tmp/* /var/tmp/* /var/cache/apt/* /var/lib/apt/lists/*; \\
    # Install conan
    python3 -m pip install conan
"""

epilogue = """
# The entry point
COPY entrypoint.py /usr/local/bin/entrypoint.py
ENTRYPOINT ["/usr/local/bin/entrypoint.py"]
SHELL ["/bin/bash", "-c"]
"""


def _gen_alternatives(alts):
    """Generate alternatives strings; takes in a list of pairs (alias-name, actual-name)"""
    res = ""
    for (alias, actual) in alts:
        rule = f"/usr/bin/{alias} {alias} {actual}"
        if not res:
            res = f"update-alternatives --install {rule} 100 "
        else:
            res += f" \\\n        --slave {rule}"
    return res


def _get_compiler_text(compilers, extra_packages=""):
    """Get the text to install the compilers and tools. `compilers` param is a dictionary: name -> ver"""
    assert "clang" in compilers or "gcc" in compilers
    alts = []
    pre_install = "apt -y update;"
    packages = ""

    if "clang" in compilers:
        v = compilers["clang"]
        llvm_apt_ver = f"{v}"
        llvm_apt_repos = []

        if v == "dev" or v >= 13:
            llvm_dev_ver = "" if v == "dev" else f"-{v}"
            llvm_apt_ver = "$(apt policy llvm 2>/dev/null | grep -E 'Candidate: 1:(.*).*$' - | cut -d':' -f3 | cut -d'.' -f1)"
            llvm_apt_repos = [
                "wget -qO - https://apt.llvm.org/llvm-snapshot.gpg.key | apt-key add -",
                f'apt-add-repository -y -n "deb http://apt.llvm.org/$(lsb_release -cs)/ llvm-toolchain-$(lsb_release -cs){llvm_dev_ver} main"'
            ]

        pre_install = ""
        if len(llvm_apt_repos) > 0:
            pre_install = "; \\\n    ".join(llvm_apt_repos) + "; \\\n    "
        pre_install += f"""apt update; \\
    v="{llvm_apt_ver}"; \\
    apt policy llvm-$v; \\
    apt policy clang-$v; \\
    apt policy clang-tidy-$v; \\
    apt policy clang-format-$v; \\
    apt policy libc++-$v-dev; \\
    apt policy libc++abi-$v-dev; \\
"""
        packages = f"""\\
        llvm-$v \\
        clang-$v \\
        clang-tidy-$v \\
        clang-format-$v \\
        libc++-$v-dev \\
        libc++abi-$v-dev"""
        alts = [
            ("clang", f"/usr/bin/clang-$v"),
            ("clang++", f"/usr/bin/clang++-$v"),
            ("clang-tidy", f"/usr/bin/clang-tidy-$v"),
            ("clang-format", f"/usr/bin/clang-format-$v"),
            ("llvm-cov", f"/usr/lib/llvm-$v/bin/llvm-cov"),
            ("run-clang-tidy", f"/usr/lib/llvm-$v/bin/run-clang-tidy"),
        ]

        # Also add alias from gcc to clang
        if "gcc" not in compilers:
            alts.extend(
                [
                    ("gcc", f"/usr/bin/clang-$v"),
                    ("g++", f"/usr/bin/clang++-$v"),
                    ("gcov", f"/usr/lib/llvm-$v/bin/llvm-cov"),
                ]
            )

    if "gcc" in compilers:
        v = compilers["gcc"]
        packages += f" g++-{v}"
        alts.extend(
            [
                ("gcc", f"/usr/bin/gcc-{v}"),
                ("g++", f"/usr/bin/g++-{v}"),
                ("gcov", f"/usr/bin/gcov-{v}"),
            ]
        )

    if extra_packages:
        packages += f" {extra_packages}"

    return f"""
# Clang and tools
RUN set -xe; \\
    {pre_install} \\
    apt install -y --no-install-recommends \\
        {packages} \\
    ; \\
    rm -rf /var/lib/apt/lists/*; \\
    {_gen_alternatives(alts)}
"""


def generate_docker(filename, base_image, compilers, extra_packages=""):
    with open(filename, "w") as f:
        f.write(f"FROM {base_image}")
        f.write(prologue)
        f.write(install_base)
        f.write(_get_compiler_text(compilers, extra_packages))
        f.write(epilogue)


def main():
    repo = os.environ.get(
        'ACTION_CXX_TOOLKIT_REPO',
        'lucteo/action-cxx-toolkit'
    )

    with open(f"docker-compose.yml", "w") as f:
        f.write("services:\n")

        for ubuntu_version in ubuntu_versions:
            gcc_versions = ubuntu_versions[ubuntu_version]["gcc_versions"]
            nvcc_versions = ubuntu_versions[ubuntu_version]["nvcc_versions"]
            nvhpc_versions = ubuntu_versions[ubuntu_version]["nvhpc_versions"]
            clang_versions = ubuntu_versions[ubuntu_version]["clang_versions"]
            # Generate the main docker file
            generate_docker(
                f"Dockerfile.main-ubuntu{ubuntu_version}",
                f"ubuntu:{ubuntu_version}",
                {"clang": clang_versions[-1], "gcc": gcc_versions[-1]},
                "curl git cppcheck iwyu lcov",
            )
            # Generate the clang docker files
            for v in clang_versions:
                generate_docker(f"Dockerfile.clang{v}-ubuntu{ubuntu_version}", f"ubuntu:{ubuntu_version}", {"clang": v})
            # Generate the gcc docker files
            for v in gcc_versions:
                generate_docker(f"Dockerfile.gcc{v}-ubuntu{ubuntu_version}", f"ubuntu:{ubuntu_version}", {"gcc": v})
                # Generate gcc + CUDA dockerfiles
                for cuda_ver in nvcc_versions:
                    generate_docker(
                        f"Dockerfile.gcc{v}-cuda{cuda_ver}-ubuntu{ubuntu_version}",
                        f"nvidia/cuda:{cuda_ver}-devel-ubuntu{ubuntu_version}",
                        {"gcc": v}
                    )
                # Generate gcc + NVHPC dockerfiles
                for nvhpc_ver in nvhpc_versions:
                    hpc_ver = nvhpc_ver["hpc_ver"]
                    cuda_ver = nvhpc_ver["cuda_ver"]
                    generate_docker(
                        f"Dockerfile.gcc{v}-cuda{cuda_ver}-nvhpc{hpc_ver}-ubuntu{ubuntu_version}",
                        f"nvcr.io/nvidia/nvhpc:{hpc_ver}-devel-cuda{cuda_ver}-ubuntu{ubuntu_version}",
                        {"gcc": v}
                    )

            f.write(f"""
  main-ubuntu{ubuntu_version}:
    image: {repo}:main-ubuntu{ubuntu_version}
    build:
      context: .
      dockerfile: Dockerfile.main-ubuntu{ubuntu_version}
    """)
            for v in clang_versions:
                f.write(f"""
  clang{v}-ubuntu{ubuntu_version}:
    image: {repo}:clang{v}-ubuntu{ubuntu_version}
    build:
      context: .
      dockerfile: Dockerfile.clang{v}-ubuntu{ubuntu_version}
    """)
            for v in gcc_versions:
                f.write(f"""
  gcc{v}-ubuntu{ubuntu_version}:
    image: {repo}:gcc{v}-ubuntu{ubuntu_version}
    build:
      context: .
      dockerfile: Dockerfile.gcc{v}-ubuntu{ubuntu_version}
    """)
                for cuda_ver in nvcc_versions:
                    f.write(f"""
  gcc{v}-cuda{cuda_ver}-ubuntu{ubuntu_version}:
    image: {repo}:gcc{v}-cuda{cuda_ver}-ubuntu{ubuntu_version}
    build:
      context: .
      dockerfile: Dockerfile.gcc{v}-cuda{cuda_ver}-ubuntu{ubuntu_version}
    """)
                for nvhpc_ver in nvhpc_versions:
                    hpc_ver = nvhpc_ver["hpc_ver"]
                    cuda_ver = nvhpc_ver["cuda_ver"]
                    f.write(f"""
  gcc{v}-cuda{cuda_ver}-nvhpc{hpc_ver}-ubuntu{ubuntu_version}:
    image: {repo}:gcc{v}-cuda{cuda_ver}-nvhpc{hpc_ver}-ubuntu{ubuntu_version}
    build:
      context: .
      dockerfile: Dockerfile.gcc{v}-cuda{cuda_ver}-nvhpc{hpc_ver}-ubuntu{ubuntu_version}
    """)

    for ubuntu_version in ubuntu_versions:
        gcc_versions = ubuntu_versions[ubuntu_version]["gcc_versions"]
        nvcc_versions = ubuntu_versions[ubuntu_version]["nvcc_versions"]
        nvhpc_versions = ubuntu_versions[ubuntu_version]["nvhpc_versions"]
        clang_versions = ubuntu_versions[ubuntu_version]["clang_versions"]

        cmd=f"DOCKER_BUILDKIT=1 docker-compose build --force-rm --parallel main-ubuntu{ubuntu_version}"
        print(cmd)
        subprocess.check_call(cmd, shell=True)

        cmd=f"DOCKER_BUILDKIT=1 docker-compose build --force-rm --parallel " + \
            " ".join([f"clang{x}-ubuntu{ubuntu_version}" for x in clang_versions])
        print(cmd)
        subprocess.check_call(cmd, shell=True)

        cmd=f"DOCKER_BUILDKIT=1 docker-compose build --force-rm --parallel " + \
            " ".join([f"gcc{x}-ubuntu{ubuntu_version}" for x in gcc_versions])
        print(cmd)
        subprocess.check_call(cmd, shell=True)

        cmd=f"DOCKER_BUILDKIT=1 docker-compose build --force-rm --parallel " + \
            " ".join([f"gcc{x}-cuda{y}-ubuntu{ubuntu_version}" for x in gcc_versions for y in nvcc_versions])
        print(cmd)
        subprocess.check_call(cmd, shell=True)

        cmd=f"DOCKER_BUILDKIT=1 docker-compose build --force-rm --parallel " + \
            " ".join([f"gcc{x}-cuda{y['cuda_ver']}-nvhpc{y['hpc_ver']}-ubuntu{ubuntu_version}" for x in gcc_versions for y in nvhpc_versions])
        print(cmd)
        subprocess.check_call(cmd, shell=True)


if __name__ == "__main__":
    main()
