import logging
import os
import posixpath
import re
import shutil
import subprocess
import tempfile

import docker
from dockerpycreds.utils import find_executable
import wandb
from wandb.errors import ExecutionException

from . import _project_spec
from .utils import WANDB_DOCKER_WORKDIR_PATH
from ..lib.git import GitRepo

_logger = logging.getLogger(__name__)

_GENERATED_DOCKERFILE_NAME = "Dockerfile.wandb-autogenerated"
_PROJECT_TAR_ARCHIVE_NAME = "wandb-project-docker-build-context"


def validate_docker_installation():
    """
    Verify if Docker is installed on host machine.
    """
    if not find_executable("docker"):
        raise ExecutionException(
            "Could not find Docker executable. "
            "Ensure Docker is installed as per the instructions "
            "at https://docs.docker.com/install/overview/."
        )


def validate_docker_env(project: _project_spec.Project):
    if not project.name:
        raise ExecutionException(
            "Project name must be specified when using docker " "for image tagging."
        )
    if not project.docker_env.get("image"):
        raise ExecutionException(
            "Project with docker environment must specify the docker image "
            "to use via an 'image' field under the 'docker_env' field."
        )


def generate_docker_image(project: _project_spec.Project, entry_cmd):
    path = project.dir
    cmd = [
        "jupyter-repo2docker",
        "--no-run",
        path,
        '"{}"'.format(entry_cmd),
    ]

    _logger.info(
        "Generating docker image from git repo or finding image if it already exists.........."
    )
    stderr = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ).stderr.decode("utf-8")
    image_id = re.findall(r"Successfully tagged (.+):latest", stderr)
    if not image_id:
        image_id = re.findall(r"Reusing existing image \((.+)\)", stderr)
    if not image_id:
        raise Exception("error running repo2docker")
    return image_id[0]


def pull_docker_image(docker_image: str):
    info = docker_image.split(":")
    client = docker.from_env()
    if len(info) == 1:
        image = client.images.pull(info[0])
    else:
        image = client.images.pull(info[0], tag=info[1])
    return image

def build_docker_image(project: _project_spec.Project, repository_uri, base_image, api, install_reqs):
    """
    Build a docker image containing the project in `work_dir`, using the base image.
    """

    image_uri = _get_docker_image_uri(
        repository_uri=repository_uri, work_dir=project.dir
    )

    wandb_project = project.docker_env["WANDB_PROJECT"]
    wandb_entity = project.docker_env["WANDB_ENTITY"]
    install_reqs_command = ""
    if install_reqs:
        path_to_reqs = os.path.abspath(os.path.join(project.dir, "requirements.txt"))
        print(project.dir)
        print(os.listdir(project.dir), os.path.exists(path_to_reqs))
        install_reqs_command = (
            f"COPY {_PROJECT_TAR_ARCHIVE_NAME}/requirements.txt requirements.txt\n"
            "RUN pip install -r requirements.txt\n"
        )
    dockerfile = (
        "FROM {imagename}\n"
        "COPY {build_context_path}/ {workdir}\n"
        "{reqs_command}"
        "WORKDIR {workdir}\n"
        "ENV WANDB_BASE_URL={base_url}\n"  # todo this is also currently passed in via r2d
        "ENV WANDB_API_KEY={api_key}\n"  # todo this is also currently passed in via r2d
        "ENV WANDB_PROJECT={wandb_project}\n"
        "ENV WANDB_ENTITY={wandb_entity}\n"
        "ENV WANDB_LAUNCH=True\n"
        "USER root\n"  # todo: very bad idea, just to get it working
    ).format(
        imagename=base_image,
        build_context_path=_PROJECT_TAR_ARCHIVE_NAME,
        workdir=WANDB_DOCKER_WORKDIR_PATH,
        reqs_command=install_reqs_command,
        base_url=api.settings("base_url"),
        api_key=api.api_key,
        wandb_project=wandb_project,
        wandb_entity=wandb_entity,
    )
    build_ctx_path = _create_docker_build_ctx(project.dir, dockerfile)
    with open(build_ctx_path, "rb") as docker_build_ctx:
        _logger.info("=== Building docker image %s ===", image_uri)
        #  TODO: replace with shelling out
        dockerfile = posixpath.join(
            _PROJECT_TAR_ARCHIVE_NAME, _GENERATED_DOCKERFILE_NAME
        )
        # TODO: remove the dependency on docker / potentially just do the append builder
        # found at: https://github.com/google/containerregistry/blob/master/client/v2_2/append_.py
        client = docker.from_env()
        image, _ = client.images.build(
            tag=image_uri,
            forcerm=True,
            dockerfile=dockerfile,
            fileobj=docker_build_ctx,
            custom_context=True,
            encoding="gzip",
        )
    try:
        os.remove(build_ctx_path)
    except Exception:
        _logger.info(
            "Temporary docker context file %s was not deleted.", build_ctx_path
        )
    return image


def _get_docker_image_uri(repository_uri, work_dir):
    """
    Returns an appropriate Docker image URI for a project based on the git hash of the specified
    working directory.
    :param repository_uri: The URI of the Docker repository with which to tag the image. The
                           repository URI is used as the prefix of the image URI.
    :param work_dir: Path to the working directory in which to search for a git commit hash
    """
    repository_uri = (
        repository_uri.replace(" ", "-") if repository_uri else "docker-project"
    )
    # Optionally include first 7 digits of git SHA in tag name, if available.

    git_commit = GitRepo(work_dir).last_commit
    version_string = ":" + git_commit[:7] if git_commit else ""
    return repository_uri + version_string


def _create_docker_build_ctx(work_dir, dockerfile_contents):
    """
    Creates build context tarfile containing Dockerfile and project code, returning path to tarfile
    """
    directory = tempfile.mkdtemp()
    try:
        dst_path = os.path.join(directory, "wandb-project-contents")
        shutil.copytree(src=work_dir, dst=dst_path)
        with open(os.path.join(dst_path, _GENERATED_DOCKERFILE_NAME), "w") as handle:
            handle.write(dockerfile_contents)
        _, result_path = tempfile.mkstemp()
        wandb.util.make_tarfile(
            output_filename=result_path,
            source_dir=dst_path,
            archive_name=_PROJECT_TAR_ARCHIVE_NAME,
        )
    finally:
        shutil.rmtree(directory)
    return result_path


def get_docker_tracking_cmd_and_envs(tracking_uri):
    cmds = []
    env_vars = dict()

    # TODO: maybe add our sweet env vars here?
    return cmds, env_vars
