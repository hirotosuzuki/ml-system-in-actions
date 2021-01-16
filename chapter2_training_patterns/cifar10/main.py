import argparse
import logging
import os
from typing import Dict
import requests
import json

import mlflow
from mlflow.utils import mlflow_tags
from mlflow.entities import RunStatus

from mlflow.tracking.fluent import _get_experiment_id

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def register_project(project_name: str, description: str = "") -> Dict:
    url = f"http://localhost:8000/v0.1/api/projects"
    response = requests.post(
        url,
        json.dumps({"project_name": project_name, "description": description}),
        headers={"Content-Type": "application/json", "accept": "application/json"},
    )
    return response.json()


def register_model(project_id: str, model_name: str, description: str = "") -> Dict:
    url = f"http://localhost:8000/v0.1/api/models"
    response = requests.post(
        url,
        json.dumps({"project_id": project_id, "model_name": model_name, "description": description}),
        headers={"Content-Type": "application/json", "accept": "application/json"},
    )
    return response.json()


def register_experiment(
    model_id: str,
    model_version_id: str,
    parameters: Dict = None,
    training_dataset: str = None,
    validation_dataset: str = None,
    test_dataset: str = None,
) -> Dict:
    url = f"http://localhost:8000/v0.1/api/experiments"
    payload = {"model_id": model_id, "model_version_id": model_version_id}
    if parameters is not None:
        payload["parameters"] = parameters
    if training_dataset is not None:
        payload["training_dataset"] = training_dataset
    if validation_dataset is not None:
        payload["validation_dataset"] = validation_dataset
    if test_dataset is not None:
        payload["test_dataset"] = test_dataset

    response = requests.post(
        url,
        json.dumps(payload),
        headers={"Content-Type": "application/json", "accept": "application/json"},
    )
    return response.json()


def main():
    parser = argparse.ArgumentParser(description="Runner", formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument("--commit_hash", type=str, default="000000", help="code commit hash")

    parser.add_argument(
        "--preprocess_data",
        type=str,
        default="cifar10",
        help="cifar10 or cifar100; default cifar10",
    )
    parser.add_argument(
        "--preprocess_downstream", type=str, default="/opt/cifar10/preprocess/", help="preprocess downstream directory"
    )
    parser.add_argument(
        "--preprocess_cached_data_id",
        type=str,
        default="",
        help="previous run id for cache",
    )

    parser.add_argument(
        "--train_upstream",
        type=str,
        default="/opt/data/preprocess",
        help="upstream directory",
    )
    parser.add_argument(
        "--train_downstream",
        type=str,
        default="/opt/cifar10/model/",
        help="downstream directory",
    )
    parser.add_argument(
        "--train_tensorboard",
        type=str,
        default="/opt/cifar10/tensorboard/",
        help="tensorboard directory",
    )
    parser.add_argument(
        "--train_epochs",
        type=int,
        default=100,
        help="epochs",
    )
    parser.add_argument(
        "--train_batch_size",
        type=int,
        default=32,
        help="batch size",
    )
    parser.add_argument(
        "--train_num_workers",
        type=int,
        default=4,
        help="number of workers",
    )
    parser.add_argument(
        "--train_learning_rate",
        type=float,
        default=0.001,
        help="learning rate",
    )
    parser.add_argument(
        "--train_model_type",
        type=str,
        default="vgg11",
        choices=["simple", "vgg11", "vgg16"],
        help="simple, vgg11 or vgg16",
    )

    parser.add_argument(
        "--building_dockerfile_path",
        type=str,
        default="/opt/data/building/Dockerfile",
        help="building Dockerfile path",
    )
    parser.add_argument(
        "--building_model_filename",
        type=str,
        default="vgg11.onnx",
        help="building model file name",
    )
    parser.add_argument(
        "--building_entrypoint_path",
        type=str,
        default="/opt/data/building/onnx_runtime_server_entrypoint.sh",
        help="building entrypoint path",
    )

    parser.add_argument(
        "--evaluate_downstream",
        type=str,
        default="/opt/data/evaluate/",
        help="evaluate downstream directory",
    )

    args = parser.parse_args()
    mlflow_experiment_id = int(os.getenv("MLFLOW_EXPERIMENT_ID", 0))

    ml_project = register_project(project_name="cifar10", description="cifar10 classification example project")
    ml_model = register_model(
        project_id=ml_project["project_id"],
        model_name="cifar10 classification",
        description="cifar10 classification model",
    )
    ml_experiment = register_experiment(
        model_id=ml_model["model_id"], model_version_id=f"cifar10_{args.commit_hash}_{mlflow_experiment_id}"
    )

    with mlflow.start_run() as r:
        preprocess_run = mlflow.run(
            uri="./preprocess",
            entry_point="preprocess",
            backend="local",
            parameters={
                "data": args.preprocess_data,
                "downstream": args.preprocess_downstream,
                "cached_data_id": args.preprocess_cached_data_id,
            },
        )
        preprocess_run = mlflow.tracking.MlflowClient().get_run(preprocess_run.run_id)

        train_run = mlflow.run(
            uri="./train",
            entry_point="train",
            backend="local",
            parameters={
                "upstream": os.path.join("/tmp/mlruns/0", preprocess_run.info.run_id, "artifacts/downstream_directory"),
                "downstream": args.train_downstream,
                "tensorboard": args.train_tensorboard,
                "epochs": args.train_epochs,
                "batch_size": args.train_batch_size,
                "num_workers": args.train_num_workers,
                "learning_rate": args.train_learning_rate,
                "model_type": args.train_model_type,
            },
        )
        train_run = mlflow.tracking.MlflowClient().get_run(train_run.run_id)

        building_run = mlflow.run(
            uri="./building",
            entry_point="building",
            backend="local",
            parameters={
                "dockerfile_path": args.building_dockerfile_path,
                "model_filename": args.building_model_filename,
                "model_directory": os.path.join("/tmp/mlruns/0", train_run.info.run_id, "artifacts"),
                "entrypoint_path": args.building_entrypoint_path,
                "dockerimage": f"shibui/ml-system-in-actions:training_pattern_cifar10_evaluate_{mlflow_experiment_id}",
            },
        )
        building_run = mlflow.tracking.MlflowClient().get_run(building_run.run_id)

        evaluate_run = mlflow.run(
            uri="./evaluate",
            entry_point="evaluate",
            backend="local",
            parameters={
                "upstream": os.path.join("/tmp/mlruns/0", train_run.info.run_id, "artifacts"),
                "downstream": args.evaluate_downstream,
                "test_data_directory": os.path.join(
                    "/tmp/mlruns/0", preprocess_run.info.run_id, "artifacts/downstream_directory/test"
                ),
                "dockerimage": f"shibui/ml-system-in-actions:training_pattern_cifar10_evaluate_{mlflow_experiment_id}",
                "container_name": f"training_pattern_cifar10_evaluate_{mlflow_experiment_id}",
            },
        )
        evaluate_run = mlflow.tracking.MlflowClient().get_run(evaluate_run.run_id)


if __name__ == "__main__":
    main()