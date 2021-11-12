import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest
import lightkube
from lightkube.generic_resource import create_global_resource

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

APP_NAME = "kfserving"
CHARM_ROOT = "."


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test):
    # build charm
    charm_under_test = await ops_test.build_charm(CHARM_ROOT)
    log.info(f"Built charm {charm_under_test}")

    # deploy charm
    image_path = METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}
    await ops_test.model.deploy(charm_under_test, resources=resources)

    # wait until active and idle
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", raise_on_blocked=True, timeout=60 * 10
    )

    # check status
    charm_status = ops_test.model.applications[APP_NAME].units[0].workload_status
    log.info(f"charm {charm_under_test} status is {charm_status}")
    assert charm_status == "active"

@pytest.mark.skip(reason="version of knative doesn't work with kfserving to allow flower deployment")
async def test_flower_predictor(ops_test: OpsTest, lightkube_client):
    pass
    # TODO: implement this test once kfserving charm and knative work properly
    # test to reproduce with pytest:
    # set -eux
    # kubectl apply -nci-test -f examples/flower.yaml
    # sleep 10
    # kubectl wait -nci-test --for=condition=available deployment --all --timeout=5m
    # ADDRESS=$(kubectl get pods -nci-test -lcomponent=predictor -oyaml \
    #   | yq e .items.0.status.podIP -)
    # curl -v \
    #   -d @examples/flower_input.json \
    #   -H "Content-Type: application/json" \
    #   http://$ADDRESS:8080/v1/models/my-model:predict
