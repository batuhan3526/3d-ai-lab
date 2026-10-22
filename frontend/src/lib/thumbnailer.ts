import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

// Tek bir gizli WebGL renderer ile mesh'ten thumbnail PNG üretir (eksik önizlemeleri
// arka planda doldurmak için). TEK context kullanır → tarayıcı context limitine takılmaz.
export function createThumbnailer(size = 320) {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setSize(size, size);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const loader = new GLTFLoader();

  async function render(url: string): Promise<Blob | null> {
    const gltf = await loader.loadAsync(url);
    const scene = new THREE.Scene();
    scene.add(gltf.scene);
    scene.add(new THREE.AmbientLight(0xffffff, 0.9));
    const dir = new THREE.DirectionalLight(0xffffff, 1.1);
    dir.position.set(3, 5, 2);
    scene.add(dir);

    // modeli kadraja al
    const box = new THREE.Box3().setFromObject(gltf.scene);
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const fov = 35;
    const cam = new THREE.PerspectiveCamera(fov, 1, 0.01, 1000);
    const dist = (sphere.radius / Math.sin((fov * Math.PI) / 180 / 2)) * 1.1;
    cam.position.set(sphere.center.x, sphere.center.y + sphere.radius * 0.15, sphere.center.z + dist);
    cam.lookAt(sphere.center);

    renderer.render(scene, cam);
    const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, "image/png"));

    // belleği temizle
    scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.geometry) m.geometry.dispose();
      const mat = m.material as THREE.Material | THREE.Material[] | undefined;
      if (mat) (Array.isArray(mat) ? mat : [mat]).forEach((x) => {
        const sm = x as THREE.MeshStandardMaterial;
        sm.map?.dispose?.();
        x.dispose?.();
      });
    });
    return blob;
  }

  return { render, dispose: () => renderer.dispose() };
}
