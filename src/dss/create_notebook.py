from pathlib import Path

from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler
from lightkube import Client
from lightkube.core.exceptions import ApiError
from lightkube.resources.apps_v1 import Deployment
from lightkube.resources.core_v1 import Service

from dss.config import (
    DSS_CLI_MANAGER_LABELS,
    DSS_NAMESPACE,
    FIELD_MANAGER,
    MANIFEST_TEMPLATES_LOCATION,
    NOTEBOOK_IMAGES_ALIASES,
    NOTEBOOK_PVC_NAME,
    RECOMMENDED_IMAGES_MESSAGE,
)
from dss.logger import setup_logger
from dss.remove_notebook import remove_notebook
from dss.utils import (
    ImagePullBackOffError,
    does_dss_pvc_exist,
    does_mlflow_deployment_exist,
    does_notebook_exist,
    get_mlflow_tracking_uri,
    get_service_url,
    intel_is_present_in_node,
    wait_for_deployment_ready,
)

# Set up logger
logger = setup_logger()


def create_notebook(name: str, image: str, lightkube_client: Client) -> None:
    """
    Creates a Notebook server on the Kubernetes cluster with optional GPU support.

    Args:
        name (str): The name of the notebook server.
        image (str): The OCI image used for the notebook server.
        lightkube_client (Client): The Kubernetes client used for server creation.

    Raises:
        RuntimeError: If there is a failure in notebook creation or GPU label checking.
    """
    if not does_dss_pvc_exist(lightkube_client) or not does_mlflow_deployment_exist(
        lightkube_client
    ):
        logger.debug("Failed to create notebook. DSS was not correctly initialized.")
        logger.error("Failed to create notebook. DSS was not correctly initialized.")
        logger.info("Note: You might want to run")
        logger.info("  dss status      to check the current status")
        logger.info("  dss logs --all  to view all logs")
        logger.info("  dss initialize  to install dss")
        raise RuntimeError()
    if does_notebook_exist(name, DSS_NAMESPACE, lightkube_client):
        # Assumes that the notebook server is exposed by a service of the same name.
        logger.debug(f"Failed to create Notebook. Notebook with name '{name}' already exists.")
        logger.error(f"Failed to create Notebook. Notebook with name '{name}' already exists.")
        logger.info("Please specify a different name.")
        url = get_service_url("name", DSS_NAMESPACE, lightkube_client)
        if url:
            logger.info(f"To connect to the existing notebook, go to {url}.")
        raise RuntimeError()

    manifests_file = Path(
        Path(__file__).parent, MANIFEST_TEMPLATES_LOCATION, "notebook_deployment.yaml.j2"
    )

    image_full_name = _get_notebook_image_name(image)
    config = _get_notebook_config(image_full_name, name, lightkube_client)

    k8s_resource_handler = KubernetesResourceHandler(
        field_manager=FIELD_MANAGER,
        labels=DSS_CLI_MANAGER_LABELS,
        template_files=[manifests_file],
        context=config,
        resource_types={Deployment, Service},
        lightkube_client=lightkube_client,
    )

    try:
        k8s_resource_handler.apply()

        wait_for_deployment_ready(
            lightkube_client, namespace=DSS_NAMESPACE, deployment_name=name, timeout_seconds=None
        )

        logger.info(f"Success: Notebook {name} created successfully.")
    except ApiError as err:
        logger.debug(f"Failed to create Notebook {name}: {err}.", exc_info=True)
        logger.error(f"Failed to create Notebook with error code {err.status.code}.")
        logger.info(" Check the debug logs for more details.")
        remove_notebook(name, lightkube_client)
        raise RuntimeError()
    except ImagePullBackOffError as err:
        logger.debug(f"Failed to create notebook {name}: {err}.", exc_info=True)
        logger.error(f"Failed to create notebook {name}.")
        logger.error(f"Image {image_full_name} does not exist or is not accessible.")
        logger.info(
            "Note: You might want to use some of these recommended images:\n\n"
            f"{RECOMMENDED_IMAGES_MESSAGE}"
        )
        remove_notebook(name, lightkube_client)
        raise RuntimeError()
    # Assumes that the notebook server is exposed by a service of the same name.
    url = get_service_url(name, DSS_NAMESPACE, lightkube_client)
    if url:
        logger.info(f"Access the notebook at {url}.")


def _get_notebook_config(image: str, name: str, lightkube_client: Client) -> dict:
    """Return a dictionary with the context to render the notebooks Deployment.

    Args:
        image(str): the container image to use for the Server.
        name(str): name of the notebook Server.
        lightkube_client(Client): a Kubernetes Client to get information to expand the context.
    """
    mlflow_tracking_uri = get_mlflow_tracking_uri()
    context = {
        "mlflow_tracking_uri": mlflow_tracking_uri,
        "notebook_name": name,
        "namespace": DSS_NAMESPACE,
        "notebook_image": image,
        "pvc_name": NOTEBOOK_PVC_NAME,
    }

    # Add intel_enabled to context to render with Intel GPU resource limits
    if intel_is_present_in_node(lightkube_client):
        context["intel_enabled"] = True

    return context


def _get_notebook_image_name(image: str) -> str:
    """
    Returns the image's full name if the input is a key in `NOTEBOOK_IMAGES_ALIASES`
    else it returns the input.
    """
    return NOTEBOOK_IMAGES_ALIASES.get(image, image)
