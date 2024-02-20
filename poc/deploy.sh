#!/bin/bash
set -e

echo -e "\nStep 1/3: Deploying MicroK8s snap"
sudo snap install microk8s --classic --channel=1.29/stable

sudo usermod -a -G microk8s $USER
sudo mkdir -p $HOME/.kube
sudo mkdir -p $HOME/.local/share
sudo chown -f -R $USER $HOME/.kube
sudo chown -f -R $USER $HOME/.local/share

echo -e "\nStep 2/3: Configuring MicroK8s addons"
sudo microk8s enable dns
sudo microk8s enable hostpath-storage
sudo microk8s enable rbac

echo "Waiting for microK8s addons to become ready..."
sudo microk8s.kubectl wait \
  --for=condition=available \
  --timeout 600s \
  -n kube-system \
  deployment/coredns \
  deployment/hostpath-provisioner
sudo microk8s.kubectl -n kube-system rollout status ds/calico-node

echo -e "\nStep 3/3: Configuring NVIDIA runtime"
sudo microk8s enable gpu

echo -e "\n\$ dss initialise"
sudo microk8s kubectl apply -f manifests/namespace.yaml
sudo microk8s kubectl apply -f manifests/mlflow.yaml

sudo microk8s.kubectl wait \
  --for condition=available \
  --timeout 60s \
  -n dss\
  deployment \
  -l app=dss-mlflow

echo -e "\n\$ dss start notebook"
sudo microk8s kubectl apply -f manifests/notebooks.yaml
sudo microk8s.kubectl wait \
  --for condition=available \
  --timeout 60s \
  -n dss\
  deployment \
  -l app=user-notebook-tensorflow

echo -e "\n\$ dss status"
MLFLOW_IP=$(sudo microk8s.kubectl get svc \
  -n dss \
  -o jsonpath="{.spec.clusterIP}" \
  mlflow)
NOTEBOOK_IP=$(sudo microk8s.kubectl get svc \
  -n dss \
  -o jsonpath="{.spec.clusterIP}" \
  user-notebook-tensorflow)

echo "DSS has started successfully!

For next steps you can connect to either of the following IPs and
start experimenting:

MLFlow: $MLFLOW_IP
TensorFlow Notebook: $NOTEBOOK_IP
"""
