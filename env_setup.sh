
# destroy previous set up
# juju destroy-controller uk8s --destroy-all-models
juju unregister uk8s
sudo snap remove microk8s --purge
charmcraft clean

# set up microk8s
sudo snap install microk8s --channel 1.19/stable --classic
microk8s enable dns storage rbac knative

microk8s status --wait-ready
microk8s.kubectl wait --for=condition=available --timeout=5m -nkube-system deployment/coredns deployment/hostpath-provisioner
microk8s config > ~/.kube/config  

# Install Charmcraft
sudo snap install lxd --classic
sudo lxd init --auto
sudo snap install charmcraft --classic
sudo snap refresh charmcraft --channel=latest/candidate

# Install Juju
sudo snap install juju --classic
sudo snap install juju-wait --classic
sudo snap install yq

# bootstrap
juju bootstrap microk8s uk8s
juju add-model ci-test

# build charm
charmcraft build
juju deploy ./*.charm --resource oci-image=$(yq eval '.resources.oci-image.upstream-source' metadata.yaml)