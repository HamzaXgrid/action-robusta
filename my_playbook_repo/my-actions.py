

from kubernetes import client
from hikaru.model.rel_1_26 import (
    Container,
    ObjectMeta,
    PersistentVolumeClaimVolumeSource,
    PodList,
    PodSpec,
    Volume,
    VolumeMount,
)
from robusta.api import (
    FileBlock,
    Finding,
    FindingSource,
    MarkdownBlock,
    PersistentVolumeEvent,ActionException, ErrorCodes,
    PodEvent,
    RobustaPod,
    action,
)

@action
def checkUnboundPv(event: PodEvent):
    finding = Finding(
        title="Pod unbound content",
        source=FindingSource.MANUAL,
        aggregation_key="checkUnboundPv",
    )
    if not event.get_pod():
        raise ActionException(ErrorCodes.RESOURCE_NOT_FOUND, "Failed to get the pod for deletion")
    pod=event.get_pod()
    api = client.CoreV1Api()
    podName=pod.metadata.name
    podNamespace=pod.metadata.namespace
    pod1 = api.read_namespaced_pod(name=podName, namespace=podNamespace)
    print("Pod is :", pod1)
    print("pod1 metadata",pod1.metadata)
    print("pod1 metadata name",pod1.metadata.name)
    for volume in pod.spec.volumes:
        print("volume is",volume)
        #if volume.persistent_volume_claim:
        pvc_name = pod1.spec.volumes.persistentVolumeClaim
        print("pvc is",pvc_name)
        print(f"PersistentVolumeClaim Name for Pod {podName}: {pvc_name}")
    finding.title = f"Pod Content:"
    finding.add_enrichment(
        [
            MarkdownBlock("Data on the Pod "),
        ]
        )
    event.add_finding(finding)

def List_of_Files_on_PV(event: PersistentVolumeEvent):
    finding = Finding(
        title="Persistent Volume content",
        source=FindingSource.MANUAL,
        aggregation_key="List_of_Files_on_PV",
    )
    persistentVolume = event.get_persistentvolume()
    api = client.CoreV1Api()
    persistentVolumeName = persistentVolume.metadata.name
    persistentVolumeDetails = api.read_persistent_volume(persistentVolumeName)
    if persistentVolumeDetails.spec.claim_ref is not None:# We are checking whether PV is claimed by any PVC.
        pvcName = persistentVolumeDetails.spec.claim_ref.name
        pvcNameSpace = persistentVolumeDetails.spec.claim_ref.namespace
        Pod = podsPvc(api, pvcName , pvcNameSpace)
        if Pod==None:# If no Pod claims any PVC than creates a temporary pod
            tempPod = temporaryPod(persistentVolume)
            result = tempPod.exec(f"ls -R {tempPod.spec.containers[0].volumeMounts[0].mountPath}/")
            finding.title = f"Persistent Volume Content:"
            finding.add_enrichment(
                [
                    MarkdownBlock("Data on the PV "),
                    FileBlock("Data.txt: ", result.encode()),
                ]
                )
            if tempPod is not None: # Deletes the Temporary Pod, This is necessary step as we don't want unused resources in our cluster
                tempPod.delete()
                return
        else:
            mountedVolumeName = None  # Initialize the variable  
            for volume in Pod.spec.volumes:
                if volume.persistent_volume_claim and volume.persistent_volume_claim.claim_name == pvcName :
                    mountedVolumeName = volume.name
            for containers in Pod.spec.containers:
                #container_name=Pod.containers.name
                for volumes in containers.volume_mounts: 
                    if volumes.name == mountedVolumeName:
                        podMountPath = containers.volume_mounts[0].mount_path  # We have a volume Path
                        newPodMountPath = podMountPath[1:] #Removing the Slash from the Mountpath, This part is only necessary if we are executing find command inside the pod instead of ls
                        #break
            namespace = pvcNameSpace
            podName = Pod.metadata.name
            podExec=getPodToExecCommand(podName,namespace)
            listOfFiles = podExec.exec(f"ls -R {newPodMountPath}/")
            event.add_enrichment([
                MarkdownBlock("The Name of The PV is "  + mountedVolumeName),
                FileBlock("FilesList.log", listOfFiles)
            ])
            finding.title = f"Persistent Volume Content: "
            finding.add_enrichment(
                [
                    FileBlock("Data.txt: ", listOfFiles.encode()),
                ]
            )
    else:
        finding.title = f"Persistent Volume Content: "
        event.add_enrichment([
            MarkdownBlock("PV is not claimed by any PVC"),
        ])
    event.add_finding(finding)


def podsPvc(api, pvcName , pvcNameSpace):#Returns the POD that claimed the PVC passed in the function
    try:
        pvc = api.read_namespaced_persistent_volume_claim(pvcName , pvcNameSpace)
        if pvc.spec.volume_name:
            podList = api.list_namespaced_pod(pvcNameSpace)
            for pod in podList.items:
                for volume in pod.spec.volumes:
                    if volume.persistent_volume_claim and volume.persistent_volume_claim.claim_name == pvcName :
                        return pod
    except client.exceptions.ApiException as e:
        print(f"Error: {e}")
    return None

def temporaryPod(persistentVolume):#Creates a temporary Pod and attached the pod with the PVC
    Volumes=[Volume(name="pvc-mount",
                    persistentVolumeClaim=PersistentVolumeClaimVolumeSource(
                        claimName=persistentVolume.spec.claimRef.name
                    ),
                )
            ]
    Containers=[
                Container(
                    name="pvc-inspector",
                    image="busybox",
                    command=["tail"],
                    args=["-f", "/dev/null"],
                    volumeMounts=[
                        VolumeMount(
                            mountPath="/pvc",
                            name="pvc-mount",
                        )
                    ],
                )
            ]
    Pod_Spec = RobustaPod(
        apiVersion="v1",
        kind="Pod",
        metadata=ObjectMeta(
            name="volume-inspector",
            namespace=persistentVolume.spec.claimRef.namespace,
        ),
        spec=PodSpec(
            volumes=Volumes,
            containers=Containers,
        ),
    )
    tempPod = Pod_Spec.create()
    return tempPod

def getPodToExecCommand(podName,podNameSpace): #Returns the Pod with Specific name
    podList = PodList.listNamespacedPod(podNameSpace).obj
    pod = None
    for pod in podList.items:
        if podName==pod.metadata.name:
            return pod
    return pod








#pod.exec(f"find {newPodMountPath} -type f") 