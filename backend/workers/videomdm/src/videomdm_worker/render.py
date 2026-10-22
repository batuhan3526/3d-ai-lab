"""
Headless renderer: SMPL motion (results.npy) + optional garment GLB → mp4.

Requires:
  PYOPENGL_PLATFORM=egl  (set by launcher / worker env)
  pyrender, trimesh, moviepy

Pipeline:
  1. Load results.npy motion array [nframes, njoints, 3].
  2. Render stick-figure skeleton per frame with pyrender (EGL headless).
  3. If garment_glb is given, overlay the (rest-pose) mesh.
  4. Stack frames → mp4 via moviepy.

TODO (Task 4.1 full implementation):
  - Per-frame SMPL body mesh rendering via Rotation2xyz output.
  - Garment per-frame LBS deformation overlay.
  - Turntable camera option.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Public entry point used by worker.py
# ---------------------------------------------------------------------------

def render_motion_mp4(
    motion_npy: Path,
    out_mp4: Path,
    garment_glb: Path | None = None,
    fps: int = 20,
    width: int = 512,
    height: int = 512,
) -> Path:
    """Render a motion results.npy to an mp4 file.

    Args:
        motion_npy:  Path to results.npy produced by MotionGenerator.generate().
        out_mp4:     Output mp4 path.
        garment_glb: Optional rest-pose garment mesh (GLB). Rendered in rest
                     pose overlay for v1; full LBS deformation is Task 3.3.
        fps:         Frames per second for output video.
        width/height: Render resolution.

    Returns:
        Path to written mp4.
    """
    # results.npy is produced locally by this process — pickle is safe here.
    results = np.load(str(motion_npy), allow_pickle=True).item()
    motion = results["motion"]     # (1, njoints, 3, nframes) or (1, njoints, 3, nframes)
    length = int(results["lengths"][0])

    # motion shape: (batch=1, njoints, 3, nframes) → (nframes, njoints, 3)
    if motion.ndim == 4:
        motion = motion[0].transpose(2, 0, 1)[:length]   # (nframes, njoints, 3)
    elif motion.ndim == 3:
        motion = motion[:length]

    frames = _render_frames(motion, garment_glb=garment_glb, width=width, height=height)

    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    _write_mp4(frames, out_mp4, fps=fps)
    return out_mp4


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

_KINEMATIC_CHAIN = [
    [0, 2, 5, 8, 11],   # right leg
    [0, 1, 4, 7, 10],   # left leg
    [0, 3, 6, 9, 12, 15],  # spine + head
    [9, 14, 17, 19, 21],   # right arm
    [9, 13, 16, 18, 20],   # left arm
]


def _render_frames(
    motion: np.ndarray,
    garment_glb: Path | None,
    width: int,
    height: int,
) -> list[np.ndarray]:
    """Render each frame to an RGB numpy array using pyrender + EGL."""
    try:
        import pyrender  # noqa: PLC0415
        import trimesh   # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError(
            "pyrender/trimesh not installed in the videomdm venv. "
            "Run: pip install pyrender trimesh"
        ) from e

    scene = pyrender.Scene(bg_color=[0.1, 0.1, 0.1, 1.0], ambient_light=[0.5, 0.5, 0.5])

    # Fixed camera
    camera = pyrender.PerspectiveCamera(yfov=np.pi / 3.0)
    camera_pose = np.eye(4)
    camera_pose[:3, 3] = [0.0, 1.0, 3.5]
    scene.add(camera, pose=camera_pose)

    # Light
    light = pyrender.DirectionalLight(color=np.ones(3), intensity=3.0)
    scene.add(light, pose=camera_pose)

    # Optional garment in rest pose
    garment_node = None
    if garment_glb is not None and Path(garment_glb).exists():
        try:
            gm = trimesh.load(str(garment_glb))
            if hasattr(gm, "geometry"):
                gm = trimesh.util.concatenate(list(gm.geometry.values()))
            garment_mesh = pyrender.Mesh.from_trimesh(gm, smooth=True)
            garment_node = scene.add(garment_mesh)
        except Exception:   # noqa: BLE001
            garment_node = None  # non-fatal; render without garment

    renderer = pyrender.OffscreenRenderer(width, height)
    frames: list[np.ndarray] = []

    try:
        for frame_joints in motion:   # (njoints, 3)
            # Remove old skeleton nodes
            for node in list(scene.mesh_nodes):
                if node is not garment_node:
                    scene.remove_node(node)

            # Draw skeleton as small spheres + cylinders
            _add_skeleton_to_scene(scene, frame_joints)

            color, _ = renderer.render(scene)
            frames.append(color)  # (H, W, 3) uint8
    finally:
        renderer.delete()

    return frames


def _add_skeleton_to_scene(scene, joints: np.ndarray) -> None:
    """Add joint spheres and bone cylinders to the scene."""
    try:
        import pyrender  # noqa: PLC0415
        import trimesh   # noqa: PLC0415
    except ImportError:
        return

    sphere_material = pyrender.MetallicRoughnessMaterial(
        baseColorFactor=[0.9, 0.4, 0.1, 1.0]
    )
    bone_material = pyrender.MetallicRoughnessMaterial(
        baseColorFactor=[0.7, 0.7, 0.9, 1.0]
    )

    # Joints as spheres
    for j_pos in joints:
        sphere = trimesh.creation.icosphere(radius=0.04)
        sphere.apply_translation(j_pos)
        mesh = pyrender.Mesh.from_trimesh(sphere, material=sphere_material)
        scene.add(mesh)

    # Bones as cylinders along kinematic chain
    for chain in _KINEMATIC_CHAIN:
        for i in range(len(chain) - 1):
            p0 = joints[chain[i]]
            p1 = joints[chain[i + 1]]
            seg = p1 - p0
            length = float(np.linalg.norm(seg))
            if length < 1e-6:
                continue
            cyl = trimesh.creation.cylinder(radius=0.02, height=length)
            # Align cylinder (default along Z) to segment direction
            mid = (p0 + p1) / 2
            z_axis = np.array([0.0, 0.0, 1.0])
            direction = seg / length
            rot_axis = np.cross(z_axis, direction)
            rot_norm = np.linalg.norm(rot_axis)
            if rot_norm > 1e-6:
                rot_axis /= rot_norm
                angle = np.arccos(np.clip(np.dot(z_axis, direction), -1, 1))
                R = trimesh.transformations.rotation_matrix(angle, rot_axis)
                T = trimesh.transformations.translation_matrix(mid)
                cyl.apply_transform(T @ R)
            else:
                cyl.apply_translation(mid)
            mesh = pyrender.Mesh.from_trimesh(cyl, material=bone_material)
            scene.add(mesh)


def _write_mp4(frames: list[np.ndarray], out_path: Path, fps: int) -> None:
    """Write a list of (H, W, 3) uint8 frames to mp4 using moviepy."""
    try:
        from moviepy.editor import ImageSequenceClip  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError(
            "moviepy not installed. Run: pip install moviepy"
        ) from e

    clip = ImageSequenceClip([f for f in frames], fps=fps)
    clip.write_videofile(str(out_path), fps=fps, logger=None)
    clip.close()
