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
    print(f"\nTesting msgpack file: {file_path}")
    
    # Get file size
    file_size = os.path.getsize(file_path)
    print(f"File size: {file_size} bytes")
    
    # Read and unpack the file
    with open(file_path, 'rb') as f:
        try:
            # Read the first few bytes to check the header
            header = f.read(16)
            print("\nFirst 16 bytes:")
            print(" ".join(f"{b:02x}" for b in header))
            
            # Reset file pointer
            f.seek(0)
            
            # Create an unpacker
            print("\nTrying to unpack using streaming unpacker...")
            unpacker = msgpack.Unpacker(f, raw=False)
            
            # Get the first object (should be our root map)
            try:
                data = next(unpacker)
                print("\nSuccessfully unpacked msgpack data")
                
                # Print root keys
                print(f"\nRoot keys: {list(data.keys())}")
                
                # Print number of stop times
                if 'stop_times' in data:
                    stop_times = data['stop_times']
                    print(f"Number of stop times: {len(stop_times)}")
                    
                    # Print first stop time entry
                    if len(stop_times) > 0:
                        print("\nFirst stop time entry:")
                        print(stop_times[0])
                        
                        # Print last stop time entry
                        print("\nLast stop time entry:")
                        print(stop_times[-1])
                        
                # Check if there's any more data
                try:
                    extra = next(unpacker)
                    print("\nWARNING: Found extra data after the root object!")
                    print(f"Extra data type: {type(extra)}")
                    print("Extra data content:")
                    print(extra)
                    
                    # Try to get even more data
                    try:
                        more_extra = next(unpacker)
                        print("\nWARNING: Found even more data!")
                        print(f"More extra data type: {type(more_extra)}")
                        print("More extra data content:")
                        print(more_extra)
                    except StopIteration:
                        print("\nNo more extra data found.")
                        
                except StopIteration:
                    print("\nNo extra data found after root object.")
                    
            except StopIteration:
                print("\nError: No data found in file")
                return False
                
        except Exception as e:
            print(f"\nError unpacking msgpack data: {e}")
            
            # Try to read the remaining bytes
            f.seek(0, os.SEEK_CUR)  # Get current position
            current_pos = f.tell()
            f.seek(0, os.SEEK_END)  # Go to end
            end_pos = f.tell()
            remaining = end_pos - current_pos
            
            if remaining > 0:
                print(f"\nRemaining bytes at error: {remaining}")
                if remaining > 32:
                    f.seek(current_pos)
                    next_bytes = f.read(32)
                    print("Next 32 bytes after error point:")
                    print(" ".join(f"{b:02x}" for b in next_bytes))
            return False
            
    return True

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python test_msgpack.py <msgpack_file>")
        sys.exit(1)
        
    success = test_msgpack_file(sys.argv[1])
    sys.exit(0 if success else 1) 