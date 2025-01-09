#!/usr/bin/env python3
import msgpack
import sys
import os
import struct
import binascii

def hexdump(data, offset=0, length=None):
    """Create a hex dump of binary data."""
    if length is None:
        length = len(data)
    result = []
    for i in range(0, min(length, len(data)), 16):
        chunk = data[i:i+16]
        hex_str = ' '.join(f'{b:02x}' for b in chunk)
        ascii_str = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
        result.append(f'{i+offset:08x}  {hex_str:<48}  |{ascii_str}|')
    return '\n'.join(result)

def find_msgpack_boundaries(data):
    """Find the boundaries of msgpack objects in the data."""
    boundaries = []
    current_pos = 0
    
    while current_pos < len(data):
        try:
            unpacker = msgpack.Unpacker(raw=False)
            unpacker.feed(data[current_pos:])
            obj = next(unpacker)
            
            # Try to find where this object ends
            for i in range(current_pos + 1, len(data) + 1):
                try:
                    msgpack.unpackb(data[current_pos:i], raw=False)
                except msgpack.exceptions.ExtraData:
                    boundaries.append((current_pos, i - 1))
                    current_pos = i - 1
                    break
                except:
                    continue
            else:
                # If we get here, the object extends to the end
                boundaries.append((current_pos, len(data)))
                break
                
            if not boundaries:
                # If we couldn't find the end, move forward one byte
                current_pos += 1
        except:
            current_pos += 1
            
    return boundaries

def analyze_file(file_path):
    """Analyze the binary content of the file."""
    print(f"\nAnalyzing file: {file_path}")
    file_size = os.path.getsize(file_path)
    print(f"File size: {file_size} bytes")
    
    with open(file_path, 'rb') as f:
        content = f.read()
        
        # Print first 64 bytes
        print("\nFirst 64 bytes:")
        print(hexdump(content, 0, 64))
        
        # Print last 64 bytes
        if len(content) > 64:
            print("\nLast 64 bytes:")
            print(hexdump(content, len(content)-64, 64))
            
        # Find msgpack object boundaries
        print("\nAnalyzing msgpack object boundaries:")
        boundaries = find_msgpack_boundaries(content)
        for i, (start, end) in enumerate(boundaries):
            print(f"\nObject {i}: bytes {start}-{end} (length: {end-start+1})")
            print("Start of object:")
            print(hexdump(content[start:start+32]))
            if end - start > 32:
                print("End of object:")
                print(hexdump(content[max(start,end-32):end+1], max(start,end-32)))
            
            # Try to unpack this section
            try:
                obj = msgpack.unpackb(content[start:end+1], raw=False)
                print(f"Successfully unpacked object of type: {type(obj)}")
                if isinstance(obj, dict):
                    print(f"Keys: {list(obj.keys())}")
            except Exception as e:
                print(f"Error unpacking section: {e}")
    
    return True

def validate_stop_time(stop_time):
    """Validate a single stop time entry."""
    required_fields = {'trip_id', 'stop_id', 'arrival_time', 'departure_time', 'stop_sequence'}
    
    # Check for required fields
    missing_fields = required_fields - set(stop_time.keys())
    if missing_fields:
        print(f"Warning: Missing required fields: {missing_fields}")
        return False
        
    # Validate types
    if not isinstance(stop_time['trip_id'], str):
        print(f"Error: trip_id should be string, got {type(stop_time['trip_id'])}")
        return False
    if not isinstance(stop_time['stop_id'], str):
        print(f"Error: stop_id should be string, got {type(stop_time['stop_id'])}")
        return False
    if not isinstance(stop_time['arrival_time'], str):
        print(f"Error: arrival_time should be string, got {type(stop_time['arrival_time'])}")
        return False
    if not isinstance(stop_time['departure_time'], str):
        print(f"Error: departure_time should be string, got {type(stop_time['departure_time'])}")
        return False
    if not isinstance(stop_time['stop_sequence'], int):
        print(f"Error: stop_sequence should be integer, got {type(stop_time['stop_sequence'])}")
        return False
        
    return True

def test_msgpack_file(file_path):
    """Test if a msgpack file can be properly unpacked."""
    if not analyze_file(file_path):
        return False
    
    try:
        with open(file_path, 'rb') as f:
            content = f.read()
            print(f"\nAttempting to unpack {len(content)} bytes")
            data = msgpack.unpackb(content, raw=False)
            
        print("\nSuccessfully unpacked msgpack data")
        print(f"Root keys: {list(data.keys())}")
        
        if 'stop_times' not in data:
            print("Error: Missing 'stop_times' key in root")
            return False
            
        stop_times = data['stop_times']
        if not isinstance(stop_times, list):
            print(f"Error: stop_times should be a list, got {type(stop_times)}")
            return False
            
        print(f"Number of stop times: {len(stop_times)}")
        
        if len(stop_times) > 0:
            print("\nValidating first stop time entry:")
            first_entry = stop_times[0]
            print(first_entry)
            if not validate_stop_time(first_entry):
                return False
                
            if len(stop_times) > 1:
                print("\nValidating last stop time entry:")
                last_entry = stop_times[-1]
                print(last_entry)
                if not validate_stop_time(last_entry):
                    return False
                    
            # Validate a sample of entries
            sample_size = min(10, len(stop_times))
            print(f"\nValidating random sample of {sample_size} entries...")
            import random
            sample_indices = random.sample(range(len(stop_times)), sample_size)
            for idx in sample_indices:
                if not validate_stop_time(stop_times[idx]):
                    print(f"Failed validation at index {idx}")
                    return False
                    
        print("\nAll validations passed successfully!")
        return True
        
    except Exception as e:
        print(f"Error unpacking msgpack: {str(e)}", file=sys.stderr)
        return False

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python test_msgpack.py <msgpack_file>")
        sys.exit(1)
        
    success = test_msgpack_file(sys.argv[1])
    sys.exit(0 if success else 1) 