import struct
from pathlib import Path
import lz4.block
import sys

BLOB_MAGIC_BYTES = b'XABA'
COMPRESSED_ASSEMBLY_MAGIC_BYTES = b'XALZ'
supported_versions = [1]

def error(s):
	print(s)
	exit(1)

def unpackUInt32LE(data):
	return struct.unpack('<I', data)[0]

def readUInt32(f):
	return struct.unpack('<I', f.read(4))[0]

def readUInt64(f):
	return struct.unpack('<Q', f.read(8))[0]

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
	
	with open(filePath,'r') as f:
		for line in f.read().split('\n')[1:]: # skip first line (Hash 32     Hash 64             Blob ID  Blob idx  Name)
			if line:
				# hash32,hash64,blobId,blobIndex,name
				_,_,_,blobIndex,name = line.split()
				blobIndex = int(blobIndex)
				assembliesIndexToName[blobIndex] = name
	
	return assembliesIndexToName

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
	assembliesIndexToName = readAssembliesManifest(assembliesManifestPath)
	
	outDir = Path(outDir)
	outDir.mkdir(parents=True, exist_ok=True)
	
	with open(assembliesBlobPath,'rb') as assembliesBlob:
		for AssemblyIndex, assembly in enumerate(assemblies):
			assembliesBlob.seek(assembly.dataOffset)
			assemblyData = assembliesBlob.read(assembly.dataSize)
			if assemblyData.startswith(COMPRESSED_ASSEMBLY_MAGIC_BYTES):
				# compressed assembly, need to decompress it first
				decompressedAssemblySize = unpackUInt32LE(assemblyData[8:12])
				assemblyData = lz4.block.decompress(assemblyData[12:],uncompressed_size=decompressedAssemblySize)
			assemblyName = assembliesIndexToName[AssemblyIndex]
			assemblyPath = outDir / f'{assemblyName}.dll'
			with open(assemblyPath,'wb') as assemblyFile:
				assemblyFile.write(assemblyData)

assembliesBlobPath = sys.argv[1]
assembliesManifestPath = sys.argv[2]
assembliesOutPath = sys.argv[3]
extractAssembliesBlob(assembliesBlobPath,assembliesManifestPath,assembliesOutPath)






