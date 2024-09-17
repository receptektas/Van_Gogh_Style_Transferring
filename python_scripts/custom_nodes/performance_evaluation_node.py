import time
import os
from datetime import datetime
import torch
import torch.nn as nn
import torchvision.transforms as transforms
from torchvision.models import inception_v3, Inception_V3_Weights, vgg19
import numpy as np
from skimage.metrics import structural_similarity as ssim
import traceback

class PerformanceMeasurement:
    def __init__(self):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.inception = self._load_inception()
        self.vgg = self._load_vgg()
        self.normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        self.mse_loss = nn.MSELoss()

    def _load_inception(self):
        weights = Inception_V3_Weights.DEFAULT
        model = inception_v3(weights=weights)
        model.fc = nn.Identity()  # Remove the final fully connected layer
        return model.eval().to(self.device)

    def _load_vgg(self):
        model = vgg19(pretrained=True).features
        return model.eval().to(self.device)

    def preprocess_image(self, image):
        if image.dim() == 4:  # (B, H, W, C)
            image = image.squeeze(0)  # Remove batch dimension
        if image.shape[-1] == 3:  # (H, W, 3)
            image = image.permute(2, 0, 1)  # Change to (3, H, W)
        elif image.shape[0] != 3:
            raise ValueError(f"Unexpected image shape: {image.shape}. Expected 3 channels.")
        
        image = image.float() / 255.0  # Normalize to [0, 1]
        image = image.unsqueeze(0)  # Add batch dimension
        return image.to(self.device)

    def normalize_image(self, image):
        return self.normalize(image)

    def calculate_ssim(self, image1, image2):
        img1 = self.preprocess_image(image1).cpu().numpy()
        img2 = self.preprocess_image(image2).cpu().numpy()
        return ssim(img1[0].transpose(1, 2, 0), img2[0].transpose(1, 2, 0), channel_axis=2, data_range=1.0)

    def get_inception_features(self, image):
        image = self.preprocess_image(image)
        image = torch.nn.functional.interpolate(image, size=(299, 299), mode='bilinear', align_corners=False)
        image = self.normalize_image(image)
        with torch.no_grad():
            features = self.inception(image)
        return features.squeeze()

    def calculate_feature_similarity(self, image1, image2):
        feat1 = self.get_inception_features(image1)
        feat2 = self.get_inception_features(image2)
        
        # Normalize features
        feat1 = feat1 / feat1.norm()
        feat2 = feat2 / feat2.norm()
        
        # Calculate cosine similarity
        similarity = torch.dot(feat1, feat2)
        
        return similarity.item()

    def calculate_perceptual_loss(self, image1, image2):
        img1 = self.normalize_image(self.preprocess_image(image1))
        img2 = self.normalize_image(self.preprocess_image(image2))
        
        features1 = self.vgg(img1)
        features2 = self.vgg(img2)
        
        return self.mse_loss(features1, features2).item()

    def calculate_content_loss(self, image1, image2, layer_index=22):  # layer 22 is relu4_4
        img1 = self.normalize_image(self.preprocess_image(image1))
        img2 = self.normalize_image(self.preprocess_image(image2))
        
        for i, layer in enumerate(self.vgg):
            img1 = layer(img1)
            img2 = layer(img2)
            if i == layer_index:
                break
        
        return self.mse_loss(img1, img2).item()

    def calculate_style_loss(self, image1, image2):
        img1 = self.normalize_image(self.preprocess_image(image1))
        img2 = self.normalize_image(self.preprocess_image(image2))
        
        def gram_matrix(x):
            b, c, h, w = x.size()
            features = x.view(b * c, h * w)
            gram = torch.mm(features, features.t())
            return gram.div(b * c * h * w)
        
        style_layers = [0, 5, 10, 19, 28]  # Conv layers
        style_loss = 0
        
        x1, x2 = img1, img2
        for i, layer in enumerate(self.vgg):
            x1 = layer(x1)
            x2 = layer(x2)
            if i in style_layers:
                style_loss += self.mse_loss(gram_matrix(x1), gram_matrix(x2))
        
        return style_loss.item()



class PerformanceMeasurementStartNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "original_image": ("IMAGE",),
                "input_image": ("IMAGE",),
            }
        }
    
    RETURN_TYPES = ("IMAGE", "IMAGE", "PERFORMANCE_CONTEXT")
    RETURN_NAMES = ("original_image", "input_image", "performance_context")
    FUNCTION = "start_measurement"
    CATEGORY = "performance"

    def start_measurement(self, original_image, input_image):
        context = {
            "start_time": time.time(),
            "start_gpu_memory": torch.cuda.memory_allocated() if torch.cuda.is_available() else 0
        }
        return (original_image, input_image, context)



class PerformanceMeasurementEndNode:
    def __init__(self):
        self.perf_measure = PerformanceMeasurement()

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "original_image": ("IMAGE",),
                "input_image": ("IMAGE",),
                "output_image": ("IMAGE",),
                "performance_context": ("PERFORMANCE_CONTEXT",),
            }
        }
    
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("output_image", "performance_metrics")
    FUNCTION = "end_measurement"
    CATEGORY = "performance"

    def end_measurement(self, original_image, input_image, output_image, performance_context):
        end_time = time.time()
        execution_time = end_time - performance_context["start_time"]

        gpu_usage = "N/A"
        gpu_model = "No GPU available"
        if torch.cuda.is_available():
            end_gpu_memory = torch.cuda.memory_allocated()
            gpu_memory_change = end_gpu_memory - performance_context["start_gpu_memory"]
            gpu_usage = f"{gpu_memory_change / 1024**2:.2f} MB"
            gpu_model = torch.cuda.get_device_name(0)

        performance_string = f"""Performance Metrics:
    Execution Time: {execution_time:.2f} seconds
    GPU Model: {gpu_model}
    GPU Memory Usage Change: {gpu_usage}
    ------------------------------------------\n"""

        try:
            performance_string += self._calculate_metrics(original_image, input_image, output_image)
        except Exception as e:
            performance_string += f"Error occurred during metric calculation: {str(e)}\n"
            performance_string += f"Traceback: {traceback.format_exc()}\n"
            performance_string += self._debug_image_info(original_image, input_image, output_image)

        self.log_performance(performance_string)

        return (output_image, performance_string)

    def _calculate_metrics(self, original_image, input_image, output_image):
        metrics = ""
        
        def categorize_ssim(value):
            if value > 0.98: return "Çok Yüksek Benzerlik"
            elif value > 0.95: return "Yüksek Benzerlik"
            elif value > 0.90: return "Orta Benzerlik"
            elif value > 0.80: return "Düşük Benzerlik"
            else: return "Çok Düşük Benzerlik"

        def categorize_feature_similarity(value):
            if value > 0.98: return "Çok Yüksek Benzerlik"
            elif value > 0.95: return "Yüksek Benzerlik"
            elif value > 0.90: return "Orta Benzerlik"
            elif value > 0.80: return "Düşük Benzerlik"
            else: return "Çok Düşük Benzerlik"

        def categorize_perceptual_loss(value):
            if value < 0.001: return "Çok Yüksek Benzerlik"
            elif value < 0.01: return "Yüksek Benzerlik"
            elif value < 0.1: return "Orta Benzerlik"
            elif value < 1.0: return "Düşük Benzerlik"
            else: return "Çok Düşük Benzerlik"

        def categorize_content_loss(value):
            if value < 0.01: return "Çok Yüksek Benzerlik"
            elif value < 0.1: return "Yüksek Benzerlik"
            elif value < 1.0: return "Orta Benzerlik"
            elif value < 10.0: return "Düşük Benzerlik"
            else: return "Çok Düşük Benzerlik"

        def categorize_style_loss(value):
            if value < 0.001: return "Çok Yüksek Benzerlik"
            elif value < 0.01: return "Yüksek Benzerlik"
            elif value < 0.1: return "Orta Benzerlik"
            elif value < 1.0: return "Düşük Benzerlik"
            else: return "Çok Düşük Benzerlik"

        ssim_oo = self.perf_measure.calculate_ssim(original_image, output_image)
        ssim_io = self.perf_measure.calculate_ssim(input_image, output_image)
        ssim_oi = self.perf_measure.calculate_ssim(original_image, input_image)
        feature_sim = self.perf_measure.calculate_feature_similarity(original_image, output_image)
        perceptual_loss = self.perf_measure.calculate_perceptual_loss(original_image, output_image)
        content_loss = self.perf_measure.calculate_content_loss(original_image, output_image)
        style_loss = self.perf_measure.calculate_style_loss(original_image, output_image)

        metrics += f"SSIM (Original vs Output): {ssim_oo:.4f} - {categorize_ssim(ssim_oo)}\n"
        metrics += f"Feature Similarity (Original vs Output): {feature_sim:.4f} - {categorize_feature_similarity(feature_sim)}\n"
        metrics += f"Perceptual Loss (Original vs Output): {perceptual_loss:.4f} - {categorize_perceptual_loss(perceptual_loss)}\n"
        metrics += f"Content Loss (Original vs Output): {content_loss:.4f} - {categorize_content_loss(content_loss)}\n"
        metrics += f"Style Loss (Original vs Output): {style_loss:.4f} - {categorize_style_loss(style_loss)}\n"

        return metrics

    def _debug_image_info(self, original_image, input_image, output_image):
        debug_info = "Debug Image Information:\n"
        debug_info += f"Original Image Shape: {original_image.shape}, dtype: {original_image.dtype}\n"
        debug_info += f"Input Image Shape: {input_image.shape}, dtype: {input_image.dtype}\n"
        debug_info += f"Output Image Shape: {output_image.shape}, dtype: {output_image.dtype}\n"
        return debug_info

    @staticmethod
    def log_performance(performance_string):
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "performance")
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"PerformanceLog_{timestamp}.txt"
        filepath = os.path.join(log_dir, filename)
        with open(filepath, "w") as f:
            f.write(performance_string)
        print(f"Performance log saved to: {filepath}")
        print(performance_string)  # Console'a da yazdır

NODE_CLASS_MAPPINGS = {
    "PerformanceMeasurementStartNode": PerformanceMeasurementStartNode,
    "PerformanceMeasurementEndNode": PerformanceMeasurementEndNode
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PerformanceMeasurementStartNode": "Start Performance Measurement",
    "PerformanceMeasurementEndNode": "End Performance Measurement"
}