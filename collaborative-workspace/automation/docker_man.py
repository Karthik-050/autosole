from backend.docker.manager import DockerManager

__all__ = ["DockerManager"]

if __name__ == "__main__":
    docker_manager = DockerManager()
    info = docker_manager.get_status()
    print("Docker status:", info)