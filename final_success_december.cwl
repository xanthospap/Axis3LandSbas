$graph:
- class: Workflow
  doc: Workflow doc
  id: ls-df-sb-00-v32
  inputs:
    end_date:
      type: string
    spatial_extent:
      doc: Bounding box [minLon, minLat, maxLon, maxLat] in WGS-84.
      type: string[]
    start_date:
      type: string
    thematic_service_name:
      label: Thematic service name
      type: string
  label: Workflow label
  outputs:
    execution_results:
      outputSource:
      - process/process_results
      type: Directory
  steps:
    analyse:
      in:
        end_date: end_date
        spatial_extent: spatial_extent
        start_date: start_date
      out:
      - data_analysis_results
      run: '#analyse'
    process:
      in:
        data_analysis_results: analyse/data_analysis_results
        spatial_extent: spatial_extent
      out:
      - process_results
      run: '#process'
- arguments:
  - /home/sbas/ASF_availability.py
  - --bbox
  - $(inputs.spatial_extent[0]),$(inputs.spatial_extent[1]),$(inputs.spatial_extent[2]),$(inputs.spatial_extent[3])
  - --start_date
  - $(inputs.start_date)
  - --end_date
  - $(inputs.end_date)
  baseCommand: python
  class: CommandLineTool
  hints:
    DockerRequirement:
      dockerPull: ghcr.io/hellenicspacecenter/ls-df-sb-s1:1.1
  id: analyse
  inputs:
    end_date:
      type: string
    spatial_extent:
      type: string[]
    start_date:
      type: string
  outputs:
    data_analysis_results:
      outputBinding:
        glob: .
      type: Directory
  requirements:
    NetworkAccess:
      networkAccess: true
    ResourceRequirement:
      coresMax: 1
      ramMax: 8000
- arguments:
  - /home/sbas/run_pipeline.py
  - --init
  - --force-init
  - --sbas
  - $(inputs.sbas_script)
  - --stac
  - $(inputs.stac_script)
  - --config-manager
  - /home/sbas/config_manager.py
  - --set
  - steps.step1_download_sentinel=true
  - --set
  - steps.step2_download_orbits=true
  - --set
  - steps.step3_dem_creation=true
  - --set
  - steps.step4_stack_interferograms=true
  - --set
  - steps.step5_run_stack=true
  - --set
  - steps.step6_run_mintpy=true
  - --set
  - sentinel.aoi=$(inputs.spatial_extent[0]),$(inputs.spatial_extent[1]),$(inputs.spatial_extent[2]),$(inputs.spatial_extent[3])
  - --set
  - sentinel.orbit=$(inputs.orbit)
  - --set
  - sentinel.start_date=$(inputs.start_date)
  - --set
  - sentinel.end_date=$(inputs.end_date)
  - --set
  - sentinel.path=$(inputs.sentinel_path)
  - --set
  - sentinel.frame_id=$(inputs.sentinel_frame_id)
  - --set
  - sentinel.username=$(inputs.sentinel_username)
  - --set
  - sentinel.password=$(inputs.sentinel_password)
  - --set
  - dem.bbox=$(inputs.dem_bbox)
  - --set
  - stack.bbox=$(inputs.stack_bbox)
  - --set
  - stack.reference_date=$(inputs.stack_reference_date)
  - --set
  - mintpy.reference_lalo=$(inputs.mintpy_reference_lalo)
  - --stac-raster
  - $(inputs.stac_raster)
  - --stac-hdf5
  - HDF5:"$(inputs.stac_hdf5_path)"://$(inputs.stac_hdf5_dataset)
  - --stac-collection-id
  - $(inputs.stac_collection_id)
  - --stac-item-id
  - $(inputs.stac_item_id)
  baseCommand: python
  class: CommandLineTool
  hints:
    DockerRequirement:
      dockerPull: ghcr.io/hellenicspacecenter/ls-df-sb-s1:1.1
  id: process
  inputs:
    data_analysis_results:
      type: Directory
    dem_bbox:
      default: 34 36 23 27
      doc: 'Space-separated bbox: "minLat maxLat minLon maxLon" (tool expects this
        format).'
      type: string
    end_date:
      default: '20250401'
      doc: YYYYMMDD
      type: string
    mintpy_reference_lalo:
      default: '[35.5, 24.02]'
      doc: JSON-style [lat, lon]
      type: string
    orbit:
      default: DESCENDING
      doc: ASCENDING or DESCENDING
      type: string
    sbas_script:
      default: /home/sbas/SBAS.py
      type: string
    sentinel_frame_id:
      default: ''
      type: string
    sentinel_password:
      default: VarvaraTsi1993!
      type: string
    sentinel_path:
      default: ''
      type: string
    sentinel_username:
      default: vtsironi
      type: string
    spatial_extent:
      default:
      - '24.07'
      - '35.37'
      - '24.22'
      - '35.27'
      doc: BBox [minLon, minLat, maxLon, maxLat] in WGS-84.
      type: string[]
    stac_collection_id:
      default: LS-DF
      type: string
    stac_hdf5_dataset:
      default: velocityStd
      type: string
    stac_hdf5_path:
      default: topsStack/mintpy/geo/geo_velocity.h5
      type: string
    stac_item_id:
      default: LS-DF-SB-S1
      type: string
    stac_raster:
      default: topsStack/mintpy/geo_velocity.tif
      type: string
    stac_script:
      default: /home/sbas/stac_products.py
      type: string
    stack_bbox:
      default: '[34.56, 35.89, 23.0, 26.68]'
      doc: JSON-style array string for stack bbox.
      type: string
    stack_reference_date:
      default: '20250217'
      doc: YYYYMMDD
      type: string
    start_date:
      default: '20250101'
      doc: YYYYMMDD
      type: string
  outputs:
    process_results:
      outputBinding:
        glob: .
      type: Directory
  requirements:
    NetworkAccess:
      networkAccess: true
    ResourceRequirement:
      coresMax: 2
      ramMax: 32384
$namespaces:
  s: https://schema.org/
cwlVersion: v1.2
s:softwareVersion: 0.1.2
schemas:
- http://schema.org/version/9.0/schemaorg-current-http.rdf
