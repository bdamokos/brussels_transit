#!/usr/bin/env python3
import msgpack
import sys
import os

def test_msgpack_file(file_path):
    """Test if a msgpack file can be properly unpacked."""
    print(f"Testing msgpack file: {file_path}")
    print(f"File size: {os.path.getsize(file_path)} bytes")
    
    try:
        with open(file_path, 'rb') as f:
            data = msgpack.unpackb(f.read(), raw=False)
            
        print("Successfully unpacked msgpack data")
        print(f"Root keys: {list(data.keys())}")
        if 'stop_times' in data:
            print(f"Number of stop times: {len(data['stop_times'])}")
            if len(data['stop_times']) > 0:
                print("First stop time entry:")
                print(data['stop_times'][0])
        return True
    except Exception as e:
        print(f"Error unpacking msgpack: {e}", file=sys.stderr)
        return False

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python test_msgpack.py <msgpack_file>")
        sys.exit(1)
        
    success = test_msgpack_file(sys.argv[1])
    sys.exit(0 if success else 1) 