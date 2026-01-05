"""
Custom middleware for API security.

This module handles request-level security checks:
- IP-based access control for API endpoints
- Request logging and monitoring
- Security headers injection

Note: HMAC signature verification is done at the view level
via the @api_security_required decorator for more granular control.
"""

import logging
from django.http import JsonResponse
from django.conf import settings

logger = logging.getLogger('api_middleware')


class APISecurityMiddleware:
    """
    Middleware for API security at the request level.
    
    Responsibilities:
    1. Early IP filtering (before hitting views)
    2. Add security headers to API responses
    3. Log API requests for monitoring
    
    Configure in settings.py:
        ALLOWED_API_IPS = ['1.2.3.4', '5.6.7.8']
    
    Or in .env:
        ALLOWED_API_IPS=1.2.3.4,5.6.7.8
        
    Set ALLOWED_API_IPS=* for development (NOT for production!)
    """
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only apply to /api/ paths
        if request.path.startswith('/api/'):
            client_ip = self.get_client_ip(request)
            
            # Log the request
            logger.info(f"API Request: {request.method} {request.path} from {client_ip}")
            
            # Early IP check (defense in depth - also checked in decorator)
            if not self.is_ip_allowed(client_ip):
                logger.warning(f"API blocked (middleware): IP not whitelisted: {client_ip}")
                return JsonResponse({
                    'error': 'Access denied',
                    'code': 'IP_NOT_ALLOWED'
                }, status=403)
            
            # Store IP in request for later use
            request.client_ip = client_ip
        
        response = self.get_response(request)
        
        # Add security headers to API responses
        if request.path.startswith('/api/'):
            response['X-Content-Type-Options'] = 'nosniff'
            response['X-Frame-Options'] = 'DENY'
            response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        
        return response
    
    def get_client_ip(self, request):
        """
        Get real client IP, handling proxies securely.
        
        Priority:
        1. X-Real-IP (set by trusted reverse proxy like Nginx)
        2. First IP in X-Forwarded-For (original client)
        3. REMOTE_ADDR (direct connection)
        """
        # X-Real-IP (most reliable when set by trusted proxy)
        x_real_ip = request.META.get('HTTP_X_REAL_IP')
        if x_real_ip:
            return x_real_ip.strip()
        
        # X-Forwarded-For chain
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            # First IP is the original client
            return x_forwarded_for.split(',')[0].strip()
        
        # Direct connection
        return request.META.get('REMOTE_ADDR', '')
    
    def is_ip_allowed(self, ip: str) -> bool:
        """Check if IP is in the whitelist."""
        allowed_ips = getattr(settings, 'ALLOWED_API_IPS', [])
        
        # If no whitelist configured, block all (fail secure)
        if not allowed_ips:
            return False
        
        # Allow all for development (when explicitly set)
        if '*' in allowed_ips or 'any' in allowed_ips:
            return True
        
        return ip in allowed_ips


# Alias for backward compatibility
APIIPWhitelistMiddleware = APISecurityMiddleware
