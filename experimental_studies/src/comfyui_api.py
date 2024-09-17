import requests
import subprocess
import json
import os
import sys
import time
import base64
import uuid
import random
import websocket
from PyQt5.QtGui import QImage

class ComfyUIClient:
    def __init__(self, server_url="127.0.0.1:8188"):
        self.server_url = server_url
        self.client_id = str(uuid.uuid4())
        self.ws = None

        # Sunucu durumunu kontrol et ve gerekirse başlat
        if not self.check_server():
            self.start_server()
            # Sunucunun başlamasını bekle
            if not self.wait_for_server(timeout=30):
                raise Exception("ComfyUI sunucusu başlatılamadı.")
        else:
            print("ComfyUI sunucusu zaten çalışıyor.")

        # WebSocket bağlantısını aç
        self.open_websocket_connection()

    def wait_for_server(self, timeout=30):
        """Sunucunun hazır olmasını bekler."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.check_server():
                return True
            time.sleep(1)
        return False

    def check_server(self):
        """ComfyUI sunucusunun çalışıp çalışmadığını kontrol et."""
        try:
            response = requests.get(f"http://{self.server_url}/")
            if response.status_code == 200:
                print("ComfyUI sunucusu çalışıyor.")
                return True
            else:
                print(f"Sunucudan beklenmeyen durum kodu alındı: {response.status_code}")
                return False
        except requests.exceptions.ConnectionError:
            print("ComfyUI sunucusu çalışmıyor.")
            return False

    def open_websocket_connection(self):
        """ComfyUI sunucusuna WebSocket bağlantısı aç."""
        try:
            self.ws = websocket.create_connection(f"ws://{self.server_url}/ws?clientId={self.client_id}")
            print("WebSocket bağlantısı kuruldu.")
        except Exception as e:
            print(f"WebSocket bağlantı hatası: {e}")
            raise

    def start_server(self):
        """ComfyUI sunucusunu başlat."""
        python_executable = sys.executable
        comfyui_path = r"path\to\ComfyUI"  # Sunucu yolunu güncelleyin
        subprocess.Popen([python_executable, comfyui_path])
        print("ComfyUI sunucusu başlatıldı.")

    def upload_image(self, image_path, image_name, image_type="input", overwrite=False):
        """Görüntüyü ComfyUI sunucusuna yükle."""
        with open(image_path, 'rb') as file:
            files = {
                'image': (image_name, file, 'image/png'),
            }
            data = {
                'type': image_type,
                'overwrite': str(overwrite).lower(),
            }
            response = requests.post(f"http://{self.server_url}/upload/image", files=files, data=data)
            response.raise_for_status()
            print(f"Görüntü '{image_name}' başarıyla yüklendi.")

    def queue_prompt(self, prompt):
        """İş akışını sunucuya gönder ve prompt_id al."""
        payload = {
            "prompt": prompt,
            "client_id": self.client_id,
        }
        headers = {'Content-Type': 'application/json'}
        response = requests.post(f"http://{self.server_url}/prompt", json=payload, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        prompt_id = response_data.get('prompt_id')
        if not prompt_id:
            raise ValueError("Sunucudan prompt_id alınamadı")
        print(f"Prompt kuyruğa alındı, ID: {prompt_id}")
        return prompt_id

    def get_history(self, prompt_id):
        """Belirli bir prompt_id için geçmişi al."""
        response = requests.get(f"http://{self.server_url}/history/{prompt_id}")
        response.raise_for_status()
        return response.json()

    def get_image(self, filename, subfolder, folder_type):
        """Sunucudan görüntü al."""
        params = {
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type,
        }
        response = requests.get(f"http://{self.server_url}/view", params=params)
        response.raise_for_status()
        return response.content

    def validate_workflow(self,workflow):
        """İş akışı düğümlerini doğrula ve class_type'ı kontrol et"""
        for node in workflow['nodes']:
            # Her node'un bir sözlük olup olmadığını kontrol edin
            if isinstance(node, dict):
                if 'class_type' not in node:
                    print(f"Warning: Node is missing 'class_type': {node}")
                else:
                    print(f"Valid node found with class_type: {node['class_type']}")
            else:
                print(f"Error: Node is not a dictionary: {node}")
                raise ValueError(f"Invalid node format: {node}")

    def process_image(self, input_image: QImage, upscale_size: tuple):
        """Görüntüyü ComfyUI'nın iş akışı ile işler."""
        # Giriş görüntüsünü kaydet
        image_path = 'input_image.png'
        input_image.save(image_path)

        # Görüntüyü sunucuya yükle
        self.upload_image(image_path, 'input_image.png', image_type='input', overwrite=True)

        # İş akışını yükle
        workflow_file = r"vanGogh_style_transferring_workflow.json"
        with open(workflow_file, 'r') as f:
            workflow = json.load(f)

        # İş akışını doğrula (validate)
        self.validate_workflow(workflow)

        # İş akışını güncelle
        for node in workflow['nodes']:
            # Check if node is dict
            if isinstance(node, dict):
                if node.get('type') == 'LoadImage':
                    if isinstance(node.get('inputs'), dict):
                        node['inputs']['image'] = 'input_image.png'
                elif node.get('type') == 'LatentUpscale':
                    upscale_values = node.get('widgets_values', [])
                    if isinstance(upscale_values, list) and len(upscale_values) >= 3:
                        try:
                            width = int(upscale_values[1])
                            height = int(upscale_values[2])
                            if isinstance(node.get('inputs'), dict):
                                node['inputs']['width'] = width
                                node['inputs']['height'] = height
                            else:
                                print(f"'inputs' is not a dictionary for node {node['id']}")
                        except (ValueError, TypeError) as e:
                            print(f"Invalid upscale values: {e}")
                            raise
                elif node.get('type') == 'CheckpointLoaderSimple':
                    if isinstance(node.get('inputs'), dict):
                        node['inputs']['ckpt_name'] = 'your_model_name'  # Kendi model isminizle değiştirin
            else:
                print(f"Node is not a dictionary: {node}")

        # KSampler için rastgele bir seed oluştur
        for node in workflow['nodes']:
            if isinstance(node, dict) and node.get('class_type') == 'KSampler':
                node['inputs']['seed'] = random.randint(0, 2**32 - 1)

        # Prompt'u kuyruğa al
        prompt_id = self.queue_prompt(workflow)

        # İlerlemeyi takip et
        try:
            output_image_path = self.track_progress(workflow, prompt_id)
        finally:
            # WebSocket bağlantısını kapat
            self.ws.close()

        if output_image_path:
            print("Görüntü başarıyla işlendi.")
            return output_image_path
        else:
            raise Exception("Görüntü işlenemedi.")


    def track_progress(self, workflow, prompt_id):
        """WebSocket üzerinden ilerlemeyi takip et ve çıktı görüntüsünü al."""
        node_ids = list(workflow.keys())
        finished_nodes = []

        while True:
            out = self.ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                if message['type'] == 'progress':
                    data = message['data']
                    current_step = data['value']
                    max_step = data['max']
                    print(f"K-Sampler'da ilerleme: Adım {current_step} / {max_step}")
                elif message['type'] == 'execution_cached':
                    data = message['data']
                    for node in data['nodes']:
                        if node not in finished_nodes:
                            finished_nodes.append(node)
                            print(f"İlerleme: {len(finished_nodes)}/{len(node_ids)} görev tamamlandı")
                elif message['type'] == 'executing':
                    data = message['data']
                    node = data['node']
                    if node and node not in finished_nodes:
                        finished_nodes.append(node)
                        print(f"İlerleme: {len(finished_nodes)}/{len(node_ids)} görev tamamlandı")
                    if node is None and data['prompt_id'] == prompt_id:
                        print("İşlem tamamlandı.")
                        # Çıktı görüntülerini al
                        images = self.get_output_images(prompt_id)
                        if images:
                            # Görüntüyü kaydet
                            for img in images:
                                if img['type'] == 'output':
                                    output_image_data = img['image_data']
                                    output_image_filename = img['file_name']
                                    with open(output_image_filename, 'wb') as f:
                                        f.write(output_image_data)
                                    print(f"Çıktı görüntüsü kaydedildi: {output_image_filename}")
                                    return output_image_filename
                        break
                elif message['type'] == 'error':
                    error_message = message.get('message', 'Bilinmeyen hata')
                    raise Exception(f"İşlem sırasında hata oluştu: {error_message}")
            else:
                continue

        return None

    def get_output_images(self, prompt_id):
        """Belirli bir prompt_id için çıktı görüntülerini al."""
        output_images = []
        history = self.get_history(prompt_id)[prompt_id]
        for node_id in history['outputs']:
            node_output = history['outputs'][node_id]
            if 'images' in node_output:
                for image_info in node_output['images']:
                    image_data = self.get_image(
                        image_info['filename'],
                        image_info['subfolder'],
                        image_info['type']
                    )
                    output_images.append({
                        'file_name': image_info['filename'],
                        'type': image_info['type'],
                        'image_data': image_data
                    })
        return output_images
