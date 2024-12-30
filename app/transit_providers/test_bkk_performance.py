"""Test BKK waiting times performance

Run it with python -m app.transit_providers.test_bkk_performance
"""

import asyncio
import time
from pathlib import Path
import logging
from logging.config import dictConfig
from transit_providers.hu.bkk.api import get_waiting_times, _current_waiting_times_task, _last_waiting_times_result
from transit_providers.config import get_provider_config
from config import get_config
import httpx
from google.transit import gtfs_realtime_pb2

# Setup logging
logging_config = get_config('LOGGING_CONFIG')
dictConfig(logging_config)
logger = logging.getLogger('performance')

async def test_waiting_times_performance(iterations: int = 10):
    """Test waiting times performance"""
    logger.info(f"Starting performance test with {iterations} iterations")
    
    total_time = 0
    times = []
    
    for i in range(iterations):
        start_time = time.time()
        try:
            result = await get_waiting_times()
            execution_time = time.time() - start_time
            total_time += execution_time
            times.append(execution_time)
            logger.info(f"Iteration {i+1}: {execution_time:.2f} seconds")
            
            # Log some statistics about the result
            stops = len(result.get('stops_data', {}))
            total_lines = sum(len(stop.get('lines', {})) 
                            for stop in result.get('stops_data', {}).values())
            logger.info(f"Result contains {stops} stops and {total_lines} lines")
            
        except Exception as e:
            logger.error(f"Error in iteration {i+1}: {e}")
    
    # Calculate statistics
    avg_time = total_time / iterations
    min_time = min(times)
    max_time = max(times)
    
    logger.info("Performance test results:")
    logger.info(f"Average execution time: {avg_time:.2f} seconds")
    logger.info(f"Minimum execution time: {min_time:.2f} seconds")
    logger.info(f"Maximum execution time: {max_time:.2f} seconds")
    logger.info(f"Total time for {iterations} iterations: {total_time:.2f} seconds")

async def test_timeout_handling():
    """Test that requests timeout after 29 seconds"""
    logger.info("Starting timeout test")
    
    # Save original client for restoration
    original_client = httpx.AsyncClient
    
    try:
        # Create a mock client that's very slow
        class SlowClient:
            def __init__(self, *args, **kwargs):
                pass
                
            async def __aenter__(self):
                return self
                
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
                
            async def get(self, *args, **kwargs):
                logger.info("Starting slow API call (35s)")
                try:
                    await asyncio.sleep(35)  # Simulate a very slow API call
                    logger.info("Slow API call completed (should never see this)")
                    raise Exception("This should never be reached due to timeout")
                except asyncio.CancelledError:
                    logger.info("API call was cancelled as expected")
                    # Create a mock response with minimal valid protobuf
                    feed = gtfs_realtime_pb2.FeedMessage()
                    feed.header.gtfs_realtime_version = "2.0"
                    feed.header.incrementality = 0  # FULL_DATASET
                    feed.header.timestamp = int(time.time())
                    response = MockResponse()
                    response.content = feed.SerializeToString()
                    return response

        class MockResponse:
            def __init__(self):
                self.content = None
                
            def raise_for_status(self):
                pass
        
        # Monkey patch the client
        httpx.AsyncClient = SlowClient
        
        # Clear any cached results
        global _last_waiting_times_result, _current_waiting_times_task
        _last_waiting_times_result = None
        if _current_waiting_times_task and not _current_waiting_times_task.done():
            _current_waiting_times_task.cancel()
        _current_waiting_times_task = None
        
        start_time = time.time()
        try:
            result = await get_waiting_times()
            execution_time = time.time() - start_time
            logger.info(f"Request completed in {execution_time:.2f} seconds")
            logger.info(f"Result: {result}")
            assert execution_time < 30, "Request took longer than 30 seconds"
            # Check that we get stop data with empty lines
            assert 'stops_data' in result, "Response should contain stops_data"
            for stop_id, stop_data in result['stops_data'].items():
                assert 'name' in stop_data, f"Stop {stop_id} should have a name"
                assert 'coordinates' in stop_data, f"Stop {stop_id} should have coordinates"
                assert 'lines' in stop_data, f"Stop {stop_id} should have a lines key"
                assert stop_data['lines'] == {}, f"Stop {stop_id} should have empty lines on timeout"
            logger.info("Timeout test passed successfully")
        except Exception as e:
            logger.error(f"Error in timeout test: {e}")
            raise
            
    finally:
        # Restore original client
        httpx.AsyncClient = original_client

async def test_request_coalescing():
    """Test that multiple concurrent requests share the same result"""
    logger.info("Starting request coalescing test")
    
    # Save original client for restoration
    original_client = httpx.AsyncClient
    
    try:
        # Create a mock client that's moderately slow
        class ModeratelySlowClient:
            def __init__(self, *args, **kwargs):
                pass
                
            async def __aenter__(self):
                return self
                
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
                
            async def get(self, *args, **kwargs):
                logger.info("Starting moderate API call (5s)")
                await asyncio.sleep(5)  # Simulate a 5-second API call
                logger.info("Moderate API call completed")
                
                # Create a mock response with minimal valid protobuf
                class MockResponse:
                    def __init__(self):
                        # Create an empty FeedMessage with required header
                        feed = gtfs_realtime_pb2.FeedMessage()
                        feed.header.gtfs_realtime_version = "2.0"
                        feed.header.incrementality = 0  # FULL_DATASET
                        feed.header.timestamp = int(time.time())
                        self.content = feed.SerializeToString()
                        
                    def raise_for_status(self):
                        pass
                
                return MockResponse()
        
        # Monkey patch the client
        httpx.AsyncClient = ModeratelySlowClient
        
        # Clear any cached results
        await clear_caches()
        
        # Make multiple concurrent requests
        async def make_request(request_id: int, delay: float = 0):
            if delay:
                await asyncio.sleep(delay)  # Add a small delay to ensure requests overlap
            start_time = time.time()
            result = await get_waiting_times()
            execution_time = time.time() - start_time
            logger.info(f"Request {request_id} completed in {execution_time:.2f} seconds")
            return result, execution_time
        
        # Launch 3 concurrent requests with small delays to ensure they overlap
        tasks = [
            make_request(0),  # First request starts immediately
            make_request(1, delay=0.1),  # Second request starts after 0.1s
            make_request(2, delay=0.2)  # Third request starts after 0.2s
        ]
        results = await asyncio.gather(*tasks)
        
        # Verify that all requests got the same result
        first_result = results[0][0]
        first_time = results[0][1]
        
        # First request should take ~5s
        assert first_time >= 4.5, "First request was too fast"
        
        for i, (result, execution_time) in enumerate(results[1:], 1):
            assert result == first_result, f"Request {i} got different result"
            # Subsequent requests should be faster as they share the result
            assert execution_time < first_time, f"Request {i} was not faster than first request"
            logger.info(f"Request {i} execution time: {execution_time:.2f}s")
            
    finally:
        # Restore original client
        httpx.AsyncClient = original_client

async def clear_caches():
    """Clear all caches between tests"""
    global _last_waiting_times_result, _current_waiting_times_task
    from transit_providers.hu.bkk.api import (
        _last_waiting_times_result as api_last_result,
        _current_waiting_times_task as api_current_task,
        _stops_cache, _routes_cache, _stops_cache_update, _routes_cache_update,
        _stop_times_cache, _last_cache_update
    )
    
    # Clear waiting times cache in both modules
    _last_waiting_times_result = None
    if _current_waiting_times_task and not _current_waiting_times_task.done():
        _current_waiting_times_task.cancel()
    _current_waiting_times_task = None
    
    # Clear API module caches
    api_last_result = None
    if api_current_task and not api_current_task.done():
        api_current_task.cancel()
    api_current_task = None
    
    # Clear stop and route caches
    _stops_cache.clear()
    _routes_cache.clear()
    _stops_cache_update = None
    _routes_cache_update = None
    
    # Clear stop times cache
    _stop_times_cache.clear()
    _last_cache_update = None

async def run_all_tests():
    """Run all tests"""
    logger.info("=== Starting all tests ===")
    
    logger.info("1. Testing timeout handling...")
    await clear_caches()
    await test_timeout_handling()
    
    logger.info("\n2. Testing request coalescing...")
    await clear_caches()
    await test_request_coalescing()
    
    logger.info("\n3. Testing performance...")
    await clear_caches()
    await test_waiting_times_performance(iterations=3)
    
    logger.info("\n=== All tests completed ===")

if __name__ == "__main__":
    asyncio.run(run_all_tests()) 