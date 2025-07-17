import struct
from pathlib import Path
import lz4.block
import sys
import json

BLOB_MAGIC_BYTES = b'XABA'
COMPRESSED_ASSEMBLY_MAGIC_BYTES = b'XALZ'
supported_versions = [1]

def print_assemblies(assemblies):
	for assembly in assemblies:
		print(f'name:{assembly.name} | lec:{assembly.localStoreIndex} | offset:{assembly.dataOffset} | size:{assembly.dataSize} | hash32:{assembly.hash32}')

def error(s):
	print(s)
	exit(1)

def unpackUInt32LE(data):
	return struct.unpack('<I', data)[0]

def packUInt32LE(i):
	return struct.pack('<I',i)

def readUInt32(f):
	return struct.unpack('<I', f.read(4))[0]

def readUInt64(f):
	return struct.unpack('<Q', f.read(8))[0]

def writeDataToFile(filePath,data):
	with open(filePath,'wb') as f:
		f.write(data)

class AssemblyStoreAssembly():
	def __init__(self,localStoreIndex,dataOffset,dataSize,debugDataOffset,debugDataSize,configDataOffset,configDataSize):
		self.name = None
		self.localStoreIndex = localStoreIndex
		self.dataOffset = dataOffset
		self.dataSize = dataSize
		self.debugDataOffset = debugDataOffset
		self.debugDataSize = debugDataSize
		self.configDataOffset = configDataOffset
		self.configDataSize = configDataSize
		self.hash32 = None
		self.hash64 = None
		self.mappingIndex = None
		self.storeId = None

def readAssembliesManifest(filePath):
	assembliesIndexToName = {}
	assembliesHash32ToIndex = {}
	assembliesHash64ToIndex = {}
	
	with open(filePath,'r') as f:
		for line in f.read().split('\n')[1:]: # skip first line (Hash 32     Hash 64             Blob ID  Blob idx  Name)
			if line:
				# hash32,hash64,blobId,blobIndex,name
				hash32,hash64,_,blobIndex,name = line.split()
				hash32,hash64,blobIndex = int(hash32,16),int(hash64,16),int(blobIndex)
				assembliesIndexToName[blobIndex] = name
				assembliesHash32ToIndex[hash32] = blobIndex
				assembliesHash64ToIndex[hash64] = blobIndex
	
	return assembliesIndexToName,assembliesHash32ToIndex,assembliesHash64ToIndex

def readAssembliesBlobMetadata(filePath):
	assemblies = []
	
	with open(filePath,'rb') as f:
		magic_bytes = f.read(4) # magic number 'XABA'
		if magic_bytes != BLOB_MAGIC_BYTES:
			error(f"magic bytes should be '{BLOB_MAGIC_BYTES}', not '{magic_bytes}.'")
		
		version = readUInt32(f)
		if version not in supported_versions:
			error(f"magic bytes should be '{BLOB_MAGIC_BYTES}', not '{magic_bytes}.'")
		
		localEntryCount = readUInt32(f)
		globalEntryCount = readUInt32(f)
		storeId = readUInt32(f)
		
		for i in range(localEntryCount):
			assemblies.append(AssemblyStoreAssembly(i,readUInt32(f),readUInt32(f),readUInt32(f),readUInt32(f),readUInt32(f),readUInt32(f)))
		
		for _ in range(globalEntryCount):
			# hash32,mappingIndex,localStoreIndex,storeId
			hash32,mappingIndex,localStoreIndex,storeId = readUInt64(f),readUInt32(f),readUInt32(f),readUInt32(f)
			assemblies[localStoreIndex].hash32 = hash32
			assemblies[localStoreIndex].mappingIndex = mappingIndex
			assemblies[localStoreIndex].storeId = storeId
		
		for _ in range(globalEntryCount):
			# hash64,mappingIndex,localStoreIndex,storeId
			hash64,_,localStoreIndex,_ = readUInt64(f),readUInt32(f),readUInt32(f),readUInt32(f)
			assemblies[localStoreIndex].hash64 = hash64
		
		
	
	return assemblies	

def extractAssembliesBlob(assembliesBlobPath,assembliesManifestPath,outDir):
	assemblies = readAssembliesBlobMetadata(assembliesBlobPath)
	assembliesIndexToName,_,_ = readAssembliesManifest(assembliesManifestPath)
	
	outDir = Path(outDir)
	outDir.mkdir(parents=True, exist_ok=True)
	assembliesCompressedDir = Path(outDir) / 'compressed'
	assembliesCompressedDir.mkdir(parents=True, exist_ok=True)
	assembliesNameToDescriptorIndex = {}
	
	with open(assembliesBlobPath,'rb') as assembliesBlob:
		for AssemblyIndex, assembly in enumerate(assemblies):
			assemblyName = assembliesIndexToName[AssemblyIndex]
			
			assembliesBlob.seek(assembly.dataOffset)
			assemblyData = assembliesBlob.read(assembly.dataSize)
			
			# compressed assembly, need to decompress it first
			if assemblyData.startswith(COMPRESSED_ASSEMBLY_MAGIC_BYTES):
				descriptorIndex = unpackUInt32LE(assemblyData[4:8])
				decompressedAssemblySize = unpackUInt32LE(assemblyData[8:12])
				assemblyData = lz4.block.decompress(assemblyData[12:],uncompressed_size=decompressedAssemblySize)
				assembliesNameToDescriptorIndex[assemblyName] = descriptorIndex
			
			assemblyPath = outDir / f'{assemblyName}.dll'
			writeDataToFile(assemblyPath, assemblyData)
			
			# there is a pdb file
			if assembly.debugDataOffset != 0 and assembly.debugDataSize != 0:
				assembliesBlob.seek(assembly.debugDataOffset)
				assemblyDebugData = assembliesBlob.read(assembly.debugDataSize)
				assemblyDebugPath = outDir / f'{assemblyName}.pdb'
				writeDataToFile(assemblyDebugPath, assemblyDebugData)
			
			# there is a config file
			if assembly.configDataOffset != 0 and assembly.configDataSize != 0:
				assembliesBlob.seek(assembly.configDataOffset)
				assemblyConfigData = assembliesBlob.read(assembly.configDataSize)
				assemblyConfigPath = outDir / f'{assemblyName}.dll.config'
				writeDataToFile(assemblyConfigPath, assemblyConfigData)
	
	# write descriptorIndex to json
	assemblyNameToDescriptorIndexJsonPath = assembliesCompressedDir / 'descriptor_index.json'
	with open(assemblyNameToDescriptorIndexJsonPath,'w') as f:
		json.dump(assembliesNameToDescriptorIndex,f)

def rebuildAssembliesBlob(assembliesBlobOutPath, assembliesManifestPath, assembliesDirPath):
	assembliesIndexToName,assembliesHash32ToIndex,assembliesHash64ToIndex = readAssembliesManifest(assembliesManifestPath)
	assembliesCount = len(assembliesIndexToName)
	assembliesDir = Path(assembliesDirPath)
	
	assembliesCompressedDir = Path(assembliesDir) / 'compressed'
	assembliesCompressedDir.mkdir(parents=True, exist_ok=True)
	assemblyNameToDescriptorIndexJsonPath = assembliesCompressedDir / 'descriptor_index.json'
	with open(assemblyNameToDescriptorIndexJsonPath,'r') as f:
		assembliesNameToDescriptorIndex = json.load(f)
	
	with open(assembliesBlobOutPath,'wb') as assembliesBlobOut:
		assembliesBlobOut.write(BLOB_MAGIC_BYTES) # magic bytes
		assembliesBlobOut.write(packUInt32LE(supported_versions[0])) # version
		assembliesBlobOut.write(packUInt32LE(assembliesCount)) # LocalEntryCount
		assembliesBlobOut.write(packUInt32LE(assembliesCount)) # GlobalEntryCount
		assembliesBlobOut.write(packUInt32LE(0)) # store id
		
		currentOffset = 20 + 64 * assembliesCount
		for index in assembliesIndexToName:
			# dll compressed file
			assemblyFilePath = assembliesDir / f'{assembliesIndexToName[index]}.dll'
			with open(assemblyFilePath,'rb') as assemblyFile:
				assemblyFileData = assemblyFile.read()
				compressedData = b'XALZ' # compressed file magic bytes
				assemblyDescriptorIndex = assembliesNameToDescriptorIndex[assembliesIndexToName[index]]
				compressedData += struct.pack('<I', assemblyDescriptorIndex) # descriptor index (ignore or idk)
				compressedData += lz4.block.compress(assemblyFileData,mode='high_compression')
				assemblyCompressedFilePath = assembliesCompressedDir / f'{assemblyFilePath.stem}.lz4'
				with open(assemblyCompressedFilePath,'wb') as assemblyCompressedFile:
					assemblyCompressedFile.write(compressedData)
				compressedDataSize = len(compressedData)
			
			assembliesBlobOut.write(packUInt32LE(currentOffset)) # DataOffset
			assembliesBlobOut.write(packUInt32LE(compressedDataSize)) # DataSize
			currentOffset += compressedDataSize
			
			# pdb file
			assemblyDebugFile = assembliesDir / f'{assembliesIndexToName[index]}.pdb'
			if assemblyDebugFile.is_file():
				assemblyDebugFileSize = assemblyDebugFile.stat().st_size
				assembliesBlobOut.write(packUInt32LE(currentOffset)) # DebugDataOffset
				assembliesBlobOut.write(packUInt32LE(assemblyDebugFileSize)) # DebugDataSize
				currentOffset += assemblyDebugFileSize
			else:
				assembliesBlobOut.write(packUInt32LE(0)) # DebugDataOffset
				assembliesBlobOut.write(packUInt32LE(0)) # DebugDataSize
			
			# config file
			assemblyConfigFile = assembliesDir / f'{assembliesIndexToName[index]}.dll.config'
			if assemblyConfigFile.is_file():
				assemblyConfigFileSize = assemblyConfigFile.stat().st_size
				assembliesBlobOut.write(packUInt32LE(currentOffset)) # ConfigDataOffset
				assembliesBlobOut.write(packUInt32LE(assemblyConfigFileSize)) # ConfigDataSize
				currentOffset += assemblyConfigFileSize
			else:
				assembliesBlobOut.write(packUInt32LE(0)) # ConfigDataOffset
				assembliesBlobOut.write(packUInt32LE(0)) # ConfigDataSize
		
		for hash32 in sorted(assembliesHash32ToIndex):
			assembliesBlobOut.write(hash32.to_bytes(4,'little') + b'\x00\x00\x00\x00') # 32 bit hash (padded with 4 bytes of zeroes)
			assembliesBlobOut.write(packUInt32LE(assembliesHash32ToIndex[hash32])) # MappingIndex
			assembliesBlobOut.write(packUInt32LE(assembliesHash32ToIndex[hash32])) # LocalStoreIndex
			assembliesBlobOut.write(packUInt32LE(0)) # StoreID
		
		for hash64 in sorted(assembliesHash64ToIndex):
			assembliesBlobOut.write(hash64.to_bytes(8,'little')) # 64 bit hash
			assembliesBlobOut.write(packUInt32LE(assembliesHash64ToIndex[hash64])) # MappingIndex
			assembliesBlobOut.write(packUInt32LE(assembliesHash64ToIndex[hash64])) # LocalStoreIndex
			assembliesBlobOut.write(packUInt32LE(0)) # StoreID
		
		for index in assembliesIndexToName:
			# dll file
			compressedAssemblyFilePath = assembliesCompressedDir / f'{assembliesIndexToName[index]}.lz4'
			with open(compressedAssemblyFilePath,'rb') as f:
				assembliesBlobOut.write(f.read())
			
			# config file
			assemblyConfigFile = assembliesDir / f'{assembliesIndexToName[index]}.dll.config'
			if assemblyConfigFile.is_file():
				with open(assemblyConfigFile,'rb') as f:
					assembliesBlobOut.write(f.read())
			
			# pdb file
			assemblyDebugFile = assembliesDir / f'{assembliesIndexToName[index]}.pdb'
			if assemblyDebugFile.is_file():
				with open(assemblyDebugFile,'rb') as f:
					assembliesBlobOut.write(f.read())

print()
if len(sys.argv) < 5:
	error('usage: xamarinBlober.py (unpack | pack) path/to/assemblies.blob path/to/assemblies.manifest path/to/output_input_folder')

mode = sys.argv[1]
assembliesBlobPath = sys.argv[2]
assembliesManifestPath = sys.argv[3]
assembliesDirPath = sys.argv[4]

if mode == 'unpack':
	extractAssembliesBlob(assembliesBlobPath,assembliesManifestPath,assembliesDirPath)
	print(f'Extracting to {assembliesDirPath} from {assembliesBlobPath} ...')
elif mode == 'pack':
	rebuildAssembliesBlob(assembliesBlobPath,assembliesManifestPath,assembliesDirPath)
	print(f'Rebuilding from {assembliesDirPath} to {assembliesBlobPath} ...')

print('Done.')
