"""
Scattergram decompression utilities for analyzer data
"""
import numpy as np
import struct
from collections import defaultdict

class HuffmanNode:
    """Node in a Huffman tree for data decompression"""
    def __init__(self, value=None, frequency=0):
        self.value = value
        self.frequency = frequency
        self.left = None
        self.right = None
    
    def is_leaf(self):
        return self.left is None and self.right is None

class ScattergramDecoder:
    """
    Handles decompression of scattergram data from analyzers
    Uses Huffman coding and Run-Length Encoding
    """
    def __init__(self, logger=None):
        self.logger = logger
    
    def log_info(self, message):
        """Log an informational message if logger is available"""
        if self.logger:
            self.logger.info(message)
        else:
            print(f"[INFO] {message}")
    
    def log_error(self, message):
        """Log an error message if logger is available"""
        if self.logger:
            self.logger.error(message)
        else:
            print(f"[ERROR] {message}")
    
    def build_huffman_tree(self, frequencies):
        """
        Build a Huffman tree based on character frequencies
        
        Args:
            frequencies: Dictionary mapping byte values to their frequencies
        
        Returns:
            Root node of the Huffman tree
        """
        # Create leaf nodes for each character
        nodes = [HuffmanNode(value=value, frequency=freq) for value, freq in frequencies.items()]
        
        # Build the tree by merging nodes
        while len(nodes) > 1:
            # Sort nodes by frequency (ascending)
            nodes.sort(key=lambda x: x.frequency)
            
            # Take the two nodes with lowest frequencies
            left = nodes.pop(0)
            right = nodes.pop(0)
            
            # Create a parent node with these as children
            parent = HuffmanNode(frequency=left.frequency + right.frequency)
            parent.left = left
            parent.right = right
            
            # Add the parent back to the list
            nodes.append(parent)
        
        # Return the root of the tree
        return nodes[0] if nodes else None
    
    def extract_huffman_dict(self, huffman_header):
        """
        Extract the Huffman dictionary from the compressed data header
        
        Args:
            huffman_header: Bytes containing the Huffman frequency information
        
        Returns:
            Dictionary mapping byte values to their frequencies
        """
        frequencies = {}
        
        # Header format might vary by analyzer - this is a simplification
        i = 0
        while i < len(huffman_header):
            if i + 2 <= len(huffman_header):
                value = huffman_header[i]
                freq = huffman_header[i + 1]
                frequencies[value] = freq
            i += 2
            
        return frequencies
    
    def decompress_huffman(self, compressed_data, huffman_tree):
        """
        Decompress data using a Huffman tree
        
        Args:
            compressed_data: The compressed data bytes
            huffman_tree: Root node of the Huffman tree
        
        Returns:
            Decompressed data as bytes
        """
        result = bytearray()
        node = huffman_tree
        
        # Process each bit in the compressed data
        for byte in compressed_data:
            for i in range(7, -1, -1):  # Process MSB to LSB
                bit = (byte >> i) & 1
                node = node.right if bit else node.left
                
                if node.is_leaf():
                    result.append(node.value)
                    node = huffman_tree  # Reset to root for next code
        
        return bytes(result)
    
    def decompress_rle(self, compressed_data):
        """
        Decompress run-length encoded data
        
        Args:
            compressed_data: The RLE compressed data
        
        Returns:
            Decompressed data
        """
        result = bytearray()
        i = 0
        
        while i < len(compressed_data):
            # Get the run value and length
            value = compressed_data[i]
            i += 1
            
            # If we're at the end, just append the value
            if i >= len(compressed_data):
                result.append(value)
                break
                
            # Get run length (next byte)
            run_length = compressed_data[i]
            i += 1
            
            # Append the value run_length times
            result.extend([value] * run_length)
        
        return bytes(result)
    
    def decompress(self, compressed_data):
        """
        Main decompression function for scattergram data
        
        Args:
            compressed_data: Raw compressed scattergram data
        
        Returns:
            Numpy array representing the scattergram (typically 256x256)
        """
        try:
            self.log_info(f"Decompressing scattergram data, size: {len(compressed_data)} bytes")
            
            # Extract header information (format depends on analyzer)
            # This is a simplified approach - actual format would need analyzer documentation
            header_size = 16  # Example, would depend on analyzer
            
            if len(compressed_data) < header_size:
                self.log_error("Compressed data too small to contain header")
                return np.zeros((256, 256), dtype=np.uint8)
                
            header = compressed_data[:header_size]
            data = compressed_data[header_size:]
            
            # Extract dimensions from header (example)
            width = struct.unpack('<H', header[0:2])[0]  # Assuming little-endian 16-bit width
            height = struct.unpack('<H', header[2:4])[0]  # Assuming little-endian 16-bit height
            
            # Extract huffman dictionary size
            huffman_dict_size = struct.unpack('<H', header[4:6])[0]
            
            # Safety check
            if huffman_dict_size > len(data):
                self.log_error("Invalid Huffman dictionary size")
                return np.zeros((width, height), dtype=np.uint8)
                
            # Extract Huffman dictionary and compressed data
            huffman_dict_data = data[:huffman_dict_size]
            compressed_body = data[huffman_dict_size:]
            
            # Build Huffman frequency dictionary
            frequencies = self.extract_huffman_dict(huffman_dict_data)
            
            # Build Huffman tree
            huffman_tree = self.build_huffman_tree(frequencies)
            if huffman_tree is None:
                self.log_error("Failed to build Huffman tree")
                return np.zeros((width, height), dtype=np.uint8)
                
            # First step: Decompress with Huffman
            rle_data = self.decompress_huffman(compressed_body, huffman_tree)
            
            # Second step: Decompress with RLE
            decompressed_data = self.decompress_rle(rle_data)
            
            # Convert to numpy array and reshape
            if len(decompressed_data) >= width * height:
                # Reshape to 2D array
                scattergram = np.frombuffer(decompressed_data[:width*height], dtype=np.uint8).reshape((height, width))
                self.log_info(f"Successfully decompressed scattergram to shape {scattergram.shape}")
                return scattergram
            else:
                self.log_error(f"Decompressed data too small: expected {width*height}, got {len(decompressed_data)}")
                return np.zeros((width, height), dtype=np.uint8)
                
        except Exception as e:
            self.log_error(f"Error decompressing scattergram: {e}")
            return np.zeros((256, 256), dtype=np.uint8)  # Return empty scattergram on error