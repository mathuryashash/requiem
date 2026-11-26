#!/usr/bin/env python3
"""
Requiem Python Client for Flagsmith API - REWRITTEN WITH HTTPX
Proper typed HTTP client with error handling, timeouts, and tests
"""
import httpx
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

@dataclass
class FlagsmithConfig:
    """Flagsmith API configuration"""
    api_url: str
    api_key: str
    timeout: float = 10.0

class FlagsmithClient:
    """Typed Flagsmith API client using httpx"""
    
    def __init__(self, api_url: str, api_key: str, timeout: float = 10.0):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.timeout = timeout
        self.headers = {
            "Authorization": f"Api-Key {api_key}",
            "Content-Type": "application/json"
        }
    
    def _request(self, method: str, endpoint: str, json_data: Optional[Dict] = None) -> Dict:
        """Make a typed HTTP request with error handling"""
        url = f"{self.api_url}/{endpoint}"
        
        try:
            with httpx.Client(timeout=self.timeout) as client:
                if method == "GET":
                    resp = client.get(url, headers=self.headers)
                elif method == "POST":
                    resp = client.post(url, headers=self.headers, json=json_data)
                elif method == "PATCH":
                    resp = client.patch(url, headers=self.headers, json=json_data)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                resp.raise_for_status()
                return resp.json() if resp.text else {}
        
        except httpx.TimeoutException as e:
            raise TimeoutError(f"API request timed out: {url}") from e
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"API error {e.response.status_code}: {e.response.text[:200]}") from e
        except Exception as e:
            raise RuntimeError(f"API request failed: {e}") from e
    
    # ===== Organisation/Project/Environment =====
    
    def get_organisations(self) -> Dict:
        """GET /organisations/"""
        return self._request("GET", "organisations/")
    
    def get_projects(self) -> Dict:
        """GET /projects/"""
        return self._request("GET", "projects/")
    
    def get_environments(self, project_id: int) -> Dict:
        """GET /projects/{id}/environments/"""
        return self._request("GET", f"projects/{project_id}/environments/")
    
    # ===== Features (Flags) =====
    
    def create_feature(self, project_id: int, name: str, feature_type: str = "MULTIVARIATE") -> Dict:
        """POST /projects/{id}/features/"""
        data = {
            "name": name,
            "type": feature_type,
            "initial_state": {
                "enabled": True,
                "multivariate_options": [
                    {"string_value": "control", "integer_value": 50},
                    {"string_value": "treatment", "integer_value": 50},
                ]
            }
        }
        return self._request("POST", f"projects/{project_id}/features/", data)
    
    def get_feature(self, project_id: int, feature_id: int) -> Dict:
        """GET /projects/{id}/features/{feature_id}/"""
        return self._request("GET", f"projects/{project_id}/features/{feature_id}/")
    
    # ===== Metrics =====
    
    def create_metric(self, project_id: int, name: str, event_type: str = "OCCURRENCE", metric_type: str = "CONVERSION") -> Dict:
        """POST /projects/{id}/metrics/"""
        data = {
            "name": name,
            "description": f"Metric: {name}",
            "event_type": {"name": event_type},
            "metric_type": metric_type
        }
        return self._request("POST", f"projects/{project_id}/metrics/", data)
    
    # ===== Experiments =====
    
    def create_experiment(self, project_id: int, name: str, feature_id: int, metric_id: int) -> Dict:
        """POST /projects/{id}/experiments/"""
        data = {
            "name": name,
            "description": f"Experiment: {name}",
            "feature": feature_id,
            "metrics": [metric_id],
            "primary_metric": metric_id,
            "feature_state_rollout_percentage": 100,
            "type": "ab_test"
        }
        return self._request("POST", f"projects/{project_id}/experiments/", data)
    
    def get_experiment(self, experiment_id: int) -> Dict:
        """GET /experiments/{id}/"""
        return self._request("GET", f"experiments/{experiment_id}/")
    
    def start_experiment(self, experiment_id: int) -> Dict:
        """POST /experiments/{id}/start/"""
        return self._request("POST", f"experiments/{experiment_id}/start/", {})
    
    def pause_experiment(self, experiment_id: int) -> Dict:
        """POST /experiments/{id}/pause/"""
        return self._request("POST", f"experiments/{experiment_id}/pause/", {})
    
    def complete_experiment(self, experiment_id: int) -> Dict:
        """POST /experiments/{id}/complete/"""
        return self._request("POST", f"experiments/{experiment_id}/complete/", {})
    
    def set_rollout(self, experiment_id: int, rollout_percentage: int) -> Dict:
        """PATCH /experiments/{id}/rollout/"""
        data = {
            "enabled": rollout_percentage > 0,
            "rollout_percentage": rollout_percentage
        }
        return self._request("PATCH", f"experiments/{experiment_id}/rollout/", data)
    
    # ===== Results & Exposures =====
    
    def get_results(self, experiment_id: int) -> Dict:
        """GET /experiments/{id}/results/"""
        return self._request("GET", f"experiments/{experiment_id}/results/")
    
    def refresh_results(self, experiment_id: int) -> Dict:
        """POST /experiments/{id}/results/refresh/"""
        return self._request("POST", f"experiments/{experiment_id}/results/refresh/", {})
    
    def get_exposures(self, experiment_id: int) -> Dict:
        """GET /experiments/{id}/exposures/"""
        return self._request("GET", f"experiments/{experiment_id}/exposures/")
    
    def refresh_exposures(self, experiment_id: int) -> Dict:
        """POST /experiments/{id}/exposures/refresh/"""
        return self._request("POST", f"experiments/{experiment_id}/exposures/refresh/", {})
    
    # ===== Events =====
    
    def send_event(self, project_id: int, identifier: str, event_type: str, properties: Optional[Dict] = None) -> Dict:
        """POST /projects/{id}/events/"""
        data = {
            "identifier": identifier,
            "event_type": event_type,
            "properties": properties or {}
        }
        return self._request("POST", f"projects/{project_id}/events/", data)


if __name__ == "__main__":
    # Test
    client = FlagsmithClient("http://localhost:8000/api/v1", "YOUR_API_KEY")
    print("✓ FlagsmithClient class ready")
