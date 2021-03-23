#!/usr/bin/env python3

import logging
from base64 import b64encode
from glob import glob
from pathlib import Path
from subprocess import check_call

import yaml
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus

from oci_image import OCIImageResource, OCIImageResourceError

log = logging.getLogger()


class Operator(CharmBase):
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        if not self.model.unit.is_leader():
            log.info("Not a leader, skipping set_pod_spec")
            self.model.unit.status = ActiveStatus()
            return

        self._stored.set_default(**self.gen_certs())
        self.image = OCIImageResource(self, "oci-image")
        self.framework.observe(self.on.install, self.set_pod_spec)
        self.framework.observe(self.on.upgrade_charm, self.set_pod_spec)
        self.framework.observe(self.on.config_changed, self.set_pod_spec)

    def set_pod_spec(self, event):
        try:
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            log.info(e)
            return

        crds = [
            {"name": crd["metadata"]["name"], "spec": crd["spec"]}
            for crd in yaml.safe_load_all(Path("src/crds.yaml").read_text())
        ]
        cert = b64encode(self._stored.cert.encode("utf-8")).decode("utf-8")
        crds[1]["spec"]["conversion"]["webhookClientConfig"]["caBundle"] = cert

        mutating = [
            {
                "name": "inferenceservice.serving.kubeflow.org",
                "webhooks": [
                    {
                        "clientConfig": {
                            "caBundle": cert,
                            "service": {
                                "name": "kfserving-webhook-server-service",
                                "namespace": self.model.name,
                                "path": "/mutate-serving-kubeflow-org-v1alpha2-inferenceservice",
                            },
                        },
                        "failurePolicy": "Fail",
                        "name": "inferenceservice.kfserving-webhook-server.defaulter",
                        "rules": [
                            {
                                "apiGroups": ["serving.kubeflow.org"],
                                "apiVersions": ["v1alpha2"],
                                "operations": ["CREATE", "UPDATE"],
                                "resources": ["inferenceservices"],
                            }
                        ],
                    },
                    {
                        "clientConfig": {
                            "caBundle": cert,
                            "service": {
                                "name": "kfserving-webhook-server-service",
                                "namespace": self.model.name,
                                "path": "/mutate-serving-kubeflow-org-v1beta1-inferenceservice",
                            },
                        },
                        "failurePolicy": "Fail",
                        "name": "inferenceservice.kfserving-webhook-server.v1beta1.defaulter",
                        "rules": [
                            {
                                "apiGroups": ["serving.kubeflow.org"],
                                "apiVersions": ["v1beta1"],
                                "operations": ["CREATE", "UPDATE"],
                                "resources": ["inferenceservices"],
                            }
                        ],
                    },
                    {
                        "clientConfig": {
                            "caBundle": cert,
                            "service": {
                                "name": "kfserving-webhook-server-service",
                                "namespace": self.model.name,
                                "path": "/mutate-pods",
                            },
                        },
                        "failurePolicy": "Fail",
                        "name": "inferenceservice.kfserving-webhook-server.pod-mutator",
                        "namespaceSelector": {
                            "matchExpressions": [
                                {
                                    "key": "control-plane",
                                    "operator": "DoesNotExist",
                                }
                            ]
                        },
                        "objectSelector": {
                            "matchExpressions": [
                                {
                                    "key": "serving.kubeflow.org/inferenceservice",
                                    "operator": "Exists",
                                }
                            ]
                        },
                        "rules": [
                            {
                                "apiGroups": [""],
                                "apiVersions": ["v1"],
                                "operations": ["CREATE", "UPDATE"],
                                "resources": ["pods"],
                            }
                        ],
                    },
                ],
            }
        ]
        validating = [
            {
                "name": "inferenceservice.serving.kubeflow.org",
                "webhooks": [
                    {
                        "clientConfig": {
                            "caBundle": cert,
                            "service": {
                                "name": "kfserving-webhook-server-service",
                                "namespace": self.model.name,
                                "path": "/validate-serving-kubeflow-org-v1alpha2-inferenceservice",
                            },
                        },
                        "failurePolicy": "Fail",
                        "name": "inferenceservice.kfserving-webhook-server.validator",
                        "rules": [
                            {
                                "apiGroups": ["serving.kubeflow.org"],
                                "apiVersions": ["v1alpha2"],
                                "operations": ["CREATE", "UPDATE"],
                                "resources": ["inferenceservices"],
                            }
                        ],
                    },
                    {
                        "clientConfig": {
                            "caBundle": cert,
                            "service": {
                                "name": "kfserving-webhook-server-service",
                                "namespace": self.model.name,
                                "path": "/validate-serving-kubeflow-org-v1beta1-inferenceservice",
                            },
                        },
                        "failurePolicy": "Fail",
                        "name": "inferenceservice.kfserving-webhook-server.v1beta1.validator",
                        "rules": [
                            {
                                "apiGroups": ["serving.kubeflow.org"],
                                "apiVersions": ["v1beta1"],
                                "operations": ["CREATE", "UPDATE"],
                                "resources": ["inferenceservices"],
                            }
                        ],
                    },
                ],
            },
            {
                "name": "trainedmodel.serving.kubeflow.org",
                "webhooks": [
                    {
                        "clientConfig": {
                            "caBundle": cert,
                            "service": {
                                "name": "kfserving-webhook-server-service",
                                "namespace": self.model.name,
                                "path": "/validate-serving-kubeflow-org-v1alpha1-trainedmodel",
                            },
                        },
                        "failurePolicy": "Fail",
                        "name": "trainedmodel.kfserving-webhook-server.validator",
                        "rules": [
                            {
                                "apiGroups": ["serving.kubeflow.org"],
                                "apiVersions": ["v1alpha1"],
                                "operations": ["CREATE", "UPDATE"],
                                "resources": ["trainedmodels"],
                            }
                        ],
                    }
                ],
            },
        ]

        self.model.unit.status = MaintenanceStatus("Setting pod spec")
        self.model.pod.set_spec(
            {
                "version": 3,
                "serviceAccount": {
                    "roles": [
                        {
                            "global": True,
                            "rules": [
                                {
                                    "apiGroups": ["admissionregistration.k8s.io"],
                                    "resources": [
                                        "mutatingwebhookconfigurations",
                                        "validatingwebhookconfigurations",
                                    ],
                                    "verbs": [
                                        "create",
                                        "delete",
                                        "get",
                                        "list",
                                        "patch",
                                        "update",
                                        "watch",
                                    ],
                                },
                                {
                                    "apiGroups": [""],
                                    "resources": ["configmaps"],
                                    "verbs": [
                                        "create",
                                        "get",
                                        "list",
                                        "update",
                                        "watch",
                                    ],
                                },
                                {
                                    "apiGroups": [""],
                                    "resources": ["events"],
                                    "verbs": [
                                        "create",
                                        "delete",
                                        "get",
                                        "list",
                                        "patch",
                                        "update",
                                        "watch",
                                    ],
                                },
                                {
                                    "apiGroups": [""],
                                    "resources": ["namespaces"],
                                    "verbs": ["get", "list", "watch"],
                                },
                                {
                                    "apiGroups": [""],
                                    "resources": ["secrets"],
                                    "verbs": [
                                        "create",
                                        "delete",
                                        "get",
                                        "list",
                                        "patch",
                                        "update",
                                        "watch",
                                    ],
                                },
                                {
                                    "apiGroups": [""],
                                    "resources": ["serviceaccounts"],
                                    "verbs": ["get", "list", "watch"],
                                },
                                {
                                    "apiGroups": [""],
                                    "resources": ["services"],
                                    "verbs": [
                                        "create",
                                        "delete",
                                        "get",
                                        "list",
                                        "patch",
                                        "update",
                                        "watch",
                                    ],
                                },
                                {
                                    "apiGroups": ["networking.istio.io"],
                                    "resources": ["virtualservices"],
                                    "verbs": [
                                        "create",
                                        "delete",
                                        "get",
                                        "list",
                                        "patch",
                                        "update",
                                        "watch",
                                    ],
                                },
                                {
                                    "apiGroups": ["networking.istio.io"],
                                    "resources": ["virtualservices/finalizers"],
                                    "verbs": [
                                        "create",
                                        "delete",
                                        "get",
                                        "list",
                                        "patch",
                                        "update",
                                        "watch",
                                    ],
                                },
                                {
                                    "apiGroups": ["networking.istio.io"],
                                    "resources": ["virtualservices/status"],
                                    "verbs": ["get", "patch", "update"],
                                },
                                {
                                    "apiGroups": ["serving.knative.dev"],
                                    "resources": ["services"],
                                    "verbs": [
                                        "create",
                                        "delete",
                                        "get",
                                        "list",
                                        "patch",
                                        "update",
                                        "watch",
                                    ],
                                },
                                {
                                    "apiGroups": ["serving.knative.dev"],
                                    "resources": ["services/finalizers"],
                                    "verbs": [
                                        "create",
                                        "delete",
                                        "get",
                                        "list",
                                        "patch",
                                        "update",
                                        "watch",
                                    ],
                                },
                                {
                                    "apiGroups": ["serving.knative.dev"],
                                    "resources": ["services/status"],
                                    "verbs": ["get", "patch", "update"],
                                },
                                {
                                    "apiGroups": ["serving.kubeflow.org"],
                                    "resources": [
                                        "inferenceservices",
                                        "inferenceservices/finalizers",
                                    ],
                                    "verbs": [
                                        "create",
                                        "delete",
                                        "get",
                                        "list",
                                        "patch",
                                        "update",
                                        "watch",
                                    ],
                                },
                                {
                                    "apiGroups": ["serving.kubeflow.org"],
                                    "resources": ["inferenceservices/status"],
                                    "verbs": ["get", "patch", "update"],
                                },
                                {
                                    "apiGroups": ["serving.kubeflow.org"],
                                    "resources": ["trainedmodels"],
                                    "verbs": [
                                        "create",
                                        "delete",
                                        "get",
                                        "list",
                                        "patch",
                                        "update",
                                        "watch",
                                    ],
                                },
                                {
                                    "apiGroups": ["serving.kubeflow.org"],
                                    "resources": ["trainedmodels/status"],
                                    "verbs": ["get", "patch", "update"],
                                },
                            ],
                        }
                    ]
                },
                "containers": [
                    {
                        "name": "manager",
                        "command": ["/manager"],
                        "args": [
                            "--metrics-addr=127.0.0.1:8080",
                        ],
                        "imageDetails": image_details,
                        "ports": [
                            {
                                "name": "metrics",
                                "containerPort": int(self.model.config["metrics-port"]),
                            },
                            {
                                "name": "webhook",
                                "containerPort": int(self.model.config["webhook-port"]),
                            },
                        ],
                        "envConfig": {"POD_NAMESPACE": self.model.name},
                        "volumeConfig": [
                            {
                                "name": "certs",
                                "mountPath": "/tmp/k8s-webhook-server/serving-certs",
                                "files": [
                                    {
                                        "path": "tls.crt",
                                        "content": self._stored.cert,
                                    },
                                    {
                                        "path": "tls.key",
                                        "content": self._stored.key,
                                    },
                                ],
                            }
                        ],
                    }
                ],
            },
            k8s_resources={
                "kubernetesResources": {
                    "customResourceDefinitions": crds,
                    "services": [
                        {
                            "name": "kfserving-webhook-server-service",
                            "spec": {
                                "selector": {"juju-app": "kfserving"},
                                "ports": [
                                    {
                                        "protocol": "TCP",
                                        "port": 443,
                                        "targetPort": int(
                                            self.model.config["webhook-port"]
                                        ),
                                    }
                                ],
                            },
                        }
                    ],
                    "mutatingWebhookConfigurations": mutating,
                    "validatingWebhookConfigurations": validating,
                },
                "configMaps": {
                    "inferenceservice-config": {
                        Path(f).with_suffix("").name: Path(f).read_text()
                        for f in glob("src/config/*.json")
                    }
                },
            },
        )
        self.model.unit.status = ActiveStatus()

    def gen_certs(self):
        model = self.model.name
        app = self.model.app.name
        webhook = f"{app}-webhook-server-service"
        Path("/run/ssl.conf").write_text(
            f"""[ req ]
default_bits = 2048
prompt = no
default_md = sha256
req_extensions = req_ext
distinguished_name = dn
[ dn ]
C = GB
ST = Canonical
L = Canonical
O = Canonical
OU = Canonical
CN = 127.0.0.1
[ req_ext ]
subjectAltName = @alt_names
[ alt_names ]
DNS.1 = {app}
DNS.2 = {app}.{model}
DNS.3 = {app}.{model}.svc
DNS.4 = {app}.{model}.svc.cluster
DNS.5 = {app}.{model}.svc.cluster.local
DNS.6 = {webhook}
DNS.7 = {webhook}.{model}
DNS.8 = {webhook}.{model}.svc
DNS.9 = {webhook}.{model}.svc.cluster
DNS.10 = {webhook}.{model}.svc.cluster.local
IP.1 = 127.0.0.1
[ v3_ext ]
authorityKeyIdentifier=keyid,issuer:always
basicConstraints=CA:FALSE
keyUsage=keyEncipherment,dataEncipherment,digitalSignature
extendedKeyUsage=serverAuth,clientAuth
subjectAltName=@alt_names"""
        )

        check_call(["openssl", "genrsa", "-out", "/run/ca.key", "2048"])
        check_call(["openssl", "genrsa", "-out", "/run/server.key", "2048"])
        check_call(
            [
                "openssl",
                "req",
                "-x509",
                "-new",
                "-sha256",
                "-nodes",
                "-days",
                "3650",
                "-key",
                "/run/ca.key",
                "-subj",
                "/CN=127.0.0.1",
                "-out",
                "/run/ca.crt",
            ]
        )
        check_call(
            [
                "openssl",
                "req",
                "-new",
                "-sha256",
                "-key",
                "/run/server.key",
                "-out",
                "/run/server.csr",
                "-config",
                "/run/ssl.conf",
            ]
        )
        check_call(
            [
                "openssl",
                "x509",
                "-req",
                "-sha256",
                "-in",
                "/run/server.csr",
                "-CA",
                "/run/ca.crt",
                "-CAkey",
                "/run/ca.key",
                "-CAcreateserial",
                "-out",
                "/run/cert.pem",
                "-days",
                "365",
                "-extensions",
                "v3_ext",
                "-extfile",
                "/run/ssl.conf",
            ]
        )

        return {
            "cert": Path("/run/cert.pem").read_text(),
            "key": Path("/run/server.key").read_text(),
            "ca": Path("/run/ca.crt").read_text(),
        }


if __name__ == "__main__":
    main(Operator)
