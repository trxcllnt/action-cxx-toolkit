#!/usr/bin/env python3

import subprocess

clang_versions = list(range(7, 15 + 1))
gcc_versions = list(range(7, 11 + 1))
nvcc_versions = ["11.7.1", "11.8.0"]
nvhpc_versions = [
    { "hpc_ver": "22.7", "cuda_ver": "11.7"},
    { "hpc_ver": "22.7", "cuda_ver": "_multi"},
    { "hpc_ver": "22.9", "cuda_ver": "11.7"},
    { "hpc_ver": "22.9", "cuda_ver": "_multi"},
]

prologue = """

ARG DEBIAN_FRONTEND=noninteractive
ARG CMAKE_VERSION=3.24.1-0kitware1ubuntu20.04.1
"""

install_base = """
# Common package setup
RUN set -xe; \\
    # Install pacakges to allow us to install other packages
    apt-get -y update; \\
    apt-get -y install --no-install-recommends \\
        apt-transport-https ca-certificates gnupg software-properties-common wget; \\
    # Add kiware repository for CMake
    wget -O - https://apt.kitware.com/keys/kitware-archive-latest.asc 2>/dev/null | apt-key add -; \\
    apt-add-repository -y -n 'https://apt.kitware.com/ubuntu/'; \\
    apt-add-repository -y -n 'ppa:ubuntu-toolchain-r/test'; \\
    apt-get -y update; \\
    # Install generic build tools & python
    apt-get -y install --no-install-recommends \\
        pkg-config make \\
        cmake=$CMAKE_VERSION \\
        cmake-data=$CMAKE_VERSION \\
        python3 python3-pip python3-setuptools \\
        ; \\
    # Cleanup apt packages
    rm -rf /var/lib/apt/lists/*; \\
    # Install conan
    python3 -m pip install conan
"""

epilogue = """
# The entry point
COPY entrypoint.py /usr/local/bin/entrypoint.py
ENTRYPOINT ["/usr/local/bin/entrypoint.py"]
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
    pre_install = ""
    packages = ""

    if "clang" in compilers:
        v = compilers["clang"]
        llvm_dev_ver = v if v > 13 else 13
        pre_install = f"""wget -qO - https://apt.llvm.org/llvm-snapshot.gpg.key | apt-key add -; \\
    apt-add-repository -y -n "deb http://apt.llvm.org/$(lsb_release -cs)/ llvm-toolchain-$(lsb_release -cs)-{llvm_dev_ver} main"; \\
"""
        packages = f"clang++-{v} libc++-{v}-dev libc++abi-{v}-dev clang-tidy-{v} clang-format-{v}"
        alts = [
            ("clang", f"/usr/bin/clang-{v}"),
            ("clang-format", f"/usr/bin/clang-format-{v}"),
            ("clang-tidy", f"/usr/bin/clang-tidy-{v}"),
            ("run-clang-tidy", f"/usr/lib/llvm-{v}/bin/run-clang-tidy"),
        ]
        # Also add alias from gcc to clang
        if "gcc" not in compilers:
            alts.extend(
                [
                    ("gcc", f"/usr/bin/clang-{v}"),
                    ("g++", f"/usr/bin/clang++-{v}"),
                ]
            )

    if "gcc" in compilers:
        v = compilers["gcc"]
        packages += f" g++-{v}"
        alts.extend(
            [
                ("gcc", f"/usr/bin/gcc-{v}"),
                ("g++", f"/usr/bin/g++-{v}"),
            ]
        )

    if extra_packages:
        packages += f" {extra_packages}"

    return f"""
# Clang and tools
RUN set -xe; \\
    {pre_install} \\
    apt-get -y update; \\
    apt-get -y install --no-install-recommends \\
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
    # Generate the main docker file
    generate_docker(
        "Dockerfile.main",
        "ubuntu:20.04",
        {"clang": clang_versions[-1], "gcc": gcc_versions[-1]},
        "curl git cppcheck iwyu lcov",
    )
    # Generate the clang docker files
    for v in clang_versions:
        generate_docker(f"Dockerfile.clang{v}", "ubuntu:20.04", {"clang": v})
    # Generate the gcc docker files
    for v in gcc_versions:
        generate_docker(f"Dockerfile.gcc{v}", "ubuntu:20.04", {"gcc": v})
        # Generate gcc + CUDA dockerfiles
        for cuda_ver in nvcc_versions:
            generate_docker(
                f"Dockerfile.gcc{v}-cuda{cuda_ver}",
                f"nvidia/cuda:{cuda_ver}-devel-ubuntu20.04",
                {"gcc": v}
            )
        # Generate gcc + NVHPC dockerfiles
        for nvhpc_ver in nvhpc_versions:
            hpc_ver = nvhpc_ver["hpc_ver"]
            cuda_ver = nvhpc_ver["cuda_ver"]
            generate_docker(
                f"Dockerfile.gcc{v}-cuda{cuda_ver}-nvhpc{hpc_ver}",
                f"nvcr.io/nvidia/nvhpc:{hpc_ver}-devel-cuda{cuda_ver}-ubuntu20.04",
                {"gcc": v}
            )

    with open("docker-compose.yml", "w") as f:
        f.write("services:\n")
        f.write("""
  main:
    image: lucteo/action-cxx-toolkit.main
    build:
      context: .
      dockerfile: Dockerfile.main
""")
        for v in clang_versions:
            f.write(f"""
  clang{v}:
    image: lucteo/action-cxx-toolkit.clang{v}
    build:
      context: .
      dockerfile: Dockerfile.clang{v}
""")
        for v in gcc_versions:
            f.write(f"""
  gcc{v}:
    image: lucteo/action-cxx-toolkit.gcc{v}
    build:
      context: .
      dockerfile: Dockerfile.gcc{v}
""")
            for cuda_ver in nvcc_versions:
                f.write(f"""
  gcc{v}-cuda{cuda_ver}:
    image: lucteo/action-cxx-toolkit.gcc{v}-cuda{cuda_ver}
    build:
      context: .
      dockerfile: Dockerfile.gcc{v}-cuda{cuda_ver}
""")
            for nvhpc_ver in nvhpc_versions:
                hpc_ver = nvhpc_ver["hpc_ver"]
                cuda_ver = nvhpc_ver["cuda_ver"]
                f.write(f"""
  gcc{v}-cuda{cuda_ver}-nvhpc{hpc_ver}:
    image: lucteo/action-cxx-toolkit.gcc{v}-cuda{cuda_ver}-nvhpc{hpc_ver}
    build:
      context: .
      dockerfile: Dockerfile.gcc{v}-cuda{cuda_ver}-nvhpc{hpc_ver}
""")

    cmd=f"DOCKER_BUILDKIT=1 docker-compose build --force-rm --parallel main " + \
        " ".join([f"gcc{x}" for x in gcc_versions])
    print(cmd)
    subprocess.call(cmd, shell=True)

    cmd=f"DOCKER_BUILDKIT=1 docker-compose build --force-rm --parallel " + \
        " ".join([f"gcc{x}-cuda{y}" for x in gcc_versions for y in nvcc_versions])
    print(cmd)
    subprocess.call(cmd, shell=True)

    cmd=f"DOCKER_BUILDKIT=1 docker-compose build --force-rm --parallel " + \
        " ".join([f"gcc{x}-cuda{y['cuda_ver']}-nvhpc{y['hpc_ver']}" for x in gcc_versions for y in nvhpc_versions])
    print(cmd)
    subprocess.call(cmd, shell=True)

    cmd=f"DOCKER_BUILDKIT=1 docker-compose build --force-rm --parallel " + \
        " ".join([f"clang{x}" for x in clang_versions])
    print(cmd)
    subprocess.call(cmd, shell=True)


if __name__ == "__main__":
    main()
