import logging
from pathlib import Path


import time
import pytest
import yaml
from pytest_operator.plugin import OpsTest
import lightkube
from lightkube.generic_resource import create_global_resource
from lightkube import codecs

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

APP_NAME = "kfserving"
CHARM_ROOT = "."
    

@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test):
    # build charm
    my_charm = await ops_test.build_charm(CHARM_ROOT)
    log.info(f"Built charm {my_charm}")

    # deploy charm
    image_path = METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}
    await ops_test.model.deploy(
        my_charm,
        resources=resources,
    )

    # wait until active and idle
    await ops_test.model.block_until(
        lambda: all(
            (unit.workload_status == "active") and unit.agent_status == "idle"
            for _, application in ops_test.model.applications.items()
            for unit in application.units
        ),
        timeout=600,
    )


async def test_flower_predictor(ops_test: OpsTest, lightkube_client):
    raise Exception("Test not yet implemented")
    # TODO: implement this test once kfserving charm and knative work properly
    # test to reproduce with pytest:
    # set -eux
    # kubectl apply -nci-test -f examples/flower.yaml
    # sleep 10
    # kubectl wait -nci-test --for=condition=available deployment --all --timeout=5m
    # ADDRESS=$(kubectl get pods -nci-test -lcomponent=predictor -oyaml | yq e .items.0.status.podIP -)
    # curl -v \
    #   -d @examples/flower_input.json \
    #   -H "Content-Type: application/json" \
    #   http://$ADDRESS:8080/v1/models/my-model:predict


# Helpers
@pytest.fixture(scope="session")
def lightkube_client() -> lightkube.Client:
    client = lightkube.Client()
    create_global_resource(
        group="kubeflow.org", version="v1", kind="Profile", plural="profiles"
    )
    return client    