#!/usr/bin/env python3
"""
Requiem Python Client for Flagsmith API
Spike 2: Test API round trips (pause, rollout, complete, results)
"""
import json

class FlagsmithClient:
    """Minimal Flagsmith API client for Requiem"""
    
    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.headers = {"Authorization": f"Api-Key {api_key}"}
    
    def _request(self, method: str, endpoint: str, json_data=None) -> dict:
        """Make an API request using curl (simpler than requests import)"""
        import subprocess
        
        url = f"{self.api_url}/{endpoint}"
        cmd = ["curl", "-s", "-X", method, url, "-H", f"Authorization: Api-Key {self.api_key}"]
        
        if method in ["POST", "PATCH"]:
            cmd += ["-H", "Content-Type: application/json"]
            if json_data:
                cmd += ["-d", json.dumps(json_data)]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"error": result.stdout[:200]}
    
    def get_organisations(self):
        """GET /organisations/"""
        return self._request("GET", "organisations")
    
    def get_projects(self):
        """GET /projects/"""
        return self._request("GET", "projects")
    
    def get_environments(self, project_id):
        """GET /projects/{id}/environments/"""
        return self._request("GET", f"projects/{project_id}/environments")
    
    def create_feature(self, project_id, name, feature_type="STANDARD"):
        """POST /projects/{id}/features/"""
        data = {"name": name, "type": feature_type}
        return self._request("POST", f"projects/{project_id}/features", data)
    
    def create_metric(self, project_id, name, event_type="OCCURRENCE", direction="HIGHER"):
        """POST /projects/{id}/metrics/"""
        data = {
            "name": name,
            "description": f"Metric: {name}",
            "event_type": {"name": name},
            "metric_type": "CONVERSION"
        }
        return self._request("POST", f"projects/{project_id}/metrics", data)
    
    def create_experiment(self, project_id, name, feature_id, metric_id):
        """POST /projects/{id}/experiments/"""
        data = {
            "name": name,
            "description": f"Experiment: {name}",
            "feature": feature_id,
            "metrics": [metric_id],
            "primary_metric": metric_id,
            "feature_state_rollout_percentage": 50,
            "type": "ab_test"
        }
        return self._request("POST", f"projects/{project_id}/experiments", data)
    
    def start_experiment(self, experiment_id):
        """POST /experiments/{id}/start/"""
        return self._request("POST", f"experiments/{experiment_id}/start", {})
    
    def pause_experiment(self, experiment_id):
        """POST /experiments/{id}/pause/"""
        return self._request("POST", f"experiments/{experiment_id}/pause", {})
    
    def complete_experiment(self, experiment_id):
        """POST /experiments/{id}/complete/"""
        return self._request("POST", f"experiments/{experiment_id}/complete", {})
    
    def set_rollout(self, experiment_id, percentage, treatment_weight=0):
        """PATCH /experiments/{id}/rollout/"""
        data = {
            "enabled": percentage > 0,
            "rollout_percentage": percentage,
        }
        return self._request("PATCH", f"experiments/{experiment_id}/rollout", data)
    
    def get_results(self, experiment_id):
        """GET /experiments/{id}/results/"""
        return self._request("GET", f"experiments/{experiment_id}/results")
    
    def refresh_results(self, experiment_id):
        """POST /experiments/{id}/results/refresh/"""
        return self._request("POST", f"experiments/{experiment_id}/results/refresh", {})


if __name__ == "__main__":
    # Test
    client = FlagsmithClient("http://localhost:8000/api/v1", "YOUR_API_KEY")
    print("✓ FlagsmithClient class ready")
